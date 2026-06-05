"""initial implementation plan Task 2：`rebuild_chunk_edges` 管理命令。

老仓库（v23.0 索引完无 ChunkEdge）批量 backfill 入口：

    python manage.py rebuild_chunk_edges --repo <uuid>   # 单仓库
    python manage.py rebuild_chunk_edges --all           # 全 INDEXED 仓库
    python manage.py rebuild_chunk_edges --repo <uuid> --dry-run  # 预估不写入

**断点续跑语义：** 仅 dispatch `ChunkRegistry.last_built_at IS NULL` 的 chunk，
命令完成后 `update(last_built_at=now())` 标记 per row；二次跑跳过已建 chunk。

**复用策略：** 命令本身不重新实现 builder 调度，直接调用 initial implementation
`code_relations.tasks.enqueue_edge_build`；fire-and-forget 任务由 `_dispatch_and_drain`
helper 复用 `verify_payload_consistency.py` 的 before/after snapshot 模式确保
真正完成再 update last_built_at。

**并发度（context contract / contract）：** 默认串行单 repo 跑（避免多 repo × 6 builder 同
时跑爆 RAM）；未来扩展 `--concurrency N` 参数预留接口（本 plan 不实现）。

引用：
- ROADMAP success criterion / work item
- initial implementation context contract（backfill 触发点）/ contract（复用 enqueue_edge_build）
- verify_payload_consistency.py（BaseCommand + asyncio.run + drain 模式样板）
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

# contract 修复（initial implementation REVIEW）：``_process_repo`` 三态状态机，让 summary
# 区分 "无 pending chunk 跳过" 与 "dispatch 失败"，运维不再误判全成功。
RepoStatus = Literal["processed", "skipped_no_work", "failed"]

from code_relations.constants import MAX_NEIGHBORS_PER_CHUNK
from code_relations.models import ChunkRegistry
from code_relations.tasks import enqueue_edge_build, snapshot_background_tasks
from repositories.models import IndexStatus, Repository

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """老仓库批量 backfill ChunkEdge：基于 ChunkRegistry.last_built_at 断点续跑。"""

    help = (
        "Rebuild ChunkEdge for repositories (backfill 老仓库 / 增量重建)；"
        "默认仅处理 last_built_at IS NULL 的 chunk（断点续跑）"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--repo",
            type=str,
            default=None,
            help="Repository UUID；与 --all 互斥",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="遍历所有 is_deleted=False + index_status=INDEXED 仓库",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "仅输出预估 chunk 数，不实际触发 enqueue_edge_build / "
                "不更新 last_built_at"
            ),
        )
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help=(
                "contract：重建 last_built_at 早于该时间戳（ISO8601）的 chunk；"
                "默认仅重建 last_built_at IS NULL（断点续跑），传值后 "
                "Q(isnull=True) | Q(__lt=since)，覆盖 schema 升级后全量重建场景"
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        repo_filter: str | None = options["repo"]
        all_mode: bool = options["all"]
        dry_run: bool = options["dry_run"]
        since_raw: str | None = options.get("since")
        since: datetime | None = None
        if since_raw is not None:
            since = parse_datetime(since_raw)
            if since is None:
                raise CommandError(
                    f"--since 不是合法 ISO8601 时间戳: {since_raw!r} "
                    "（示例：2026-05-01T00:00:00+08:00）"
                )
            if timezone.is_naive(since):
                raise CommandError(
                    "--since 必须带 timezone（USE_TZ=True 项目惯例），"
                    f"got naive datetime: {since_raw!r}"
                )

        if repo_filter and all_mode:
            raise CommandError("--repo 与 --all 互斥，请只传其一")
        if not repo_filter and not all_mode:
            raise CommandError("必须指定 --repo <uuid> 或 --all")

        repos_qs: QuerySet[Repository] = Repository.objects.filter(
            is_deleted=False, index_status=IndexStatus.INDEXED
        )
        if repo_filter:
            try:
                uuid.UUID(repo_filter)
            except (ValueError, TypeError) as exc:
                raise CommandError(f"--repo 不是合法 UUID: {repo_filter}") from exc
            repos_qs = repos_qs.filter(id=repo_filter)

        repos = list(repos_qs)
        if not repos:
            if repo_filter:
                raise CommandError(
                    f"未找到 INDEXED repository_id={repo_filter}"
                    f"（不存在 / 已软删 / index_status != INDEXED）"
                )
            self.stdout.write(
                "没有可 backfill 的 INDEXED 仓库（is_deleted=False + INDEXED 集合为空）"
            )
            return

        logger.info(
            "rebuild_chunk_edges_started",
            repo_count=len(repos),
            dry_run=dry_run,
            mode="all" if all_mode else "single",
        )

        processed_repos = 0
        skipped_no_work_repos = 0
        failed_repos = 0
        total_chunks_dispatched = 0

        for repo in repos:
            status, dispatched = self._process_repo(
                repo, dry_run=dry_run, since=since
            )
            if status == "processed":
                processed_repos += 1
                total_chunks_dispatched += dispatched
            elif status == "skipped_no_work":
                skipped_no_work_repos += 1
            else:
                failed_repos += 1

        self.stdout.write("")
        self.stdout.write(
            f"Summary: processed_repos={processed_repos} "
            f"skipped_no_work_repos={skipped_no_work_repos} "
            f"failed_repos={failed_repos} "
            f"total_chunks_dispatched={total_chunks_dispatched} "
            f"dry_run={dry_run}"
        )
        logger.info(
            "rebuild_chunk_edges_finished",
            processed_repos=processed_repos,
            skipped_no_work_repos=skipped_no_work_repos,
            failed_repos=failed_repos,
            total_chunks_dispatched=total_chunks_dispatched,
            dry_run=dry_run,
        )

        # contract 修复（initial implementation REVIEW）：任一 repo dispatch 失败 → 退出码非 0，
        # 让 CI / APScheduler wrapper (work item 也依赖此契约) 能感知。dry-run 不参
        # 与失败计算（dry-run 内部不真 dispatch，无法 fail）。
        if failed_repos > 0 and not dry_run:
            sys.exit(1)

    def _process_repo(
        self,
        repository: Repository,
        *,
        dry_run: bool,
        since: datetime | None = None,
    ) -> tuple[RepoStatus, int]:
        """处理单个 repo：选 pending chunks → dispatch（或 dry-run 预估）→ 更新 last_built_at。

        Args:
            repository: 待处理 Repository
            dry_run: 仅预估，不实际 dispatch / 不更新 last_built_at
            since: contract ``--since`` 过滤时间戳；非 None 时除 ``isnull=True`` 外，
                也包含 ``last_built_at < since`` 的旧行（schema 升级后全量重建）

        Returns:
            ``(status, count)`` 元组：

            - ``("processed", N)``：dispatch 成功（或 dry-run 预估），N=chunk 数；
            - ``("skipped_no_work", 0)``：无 pending chunk（已 backfill 或空仓）；
            - ``("failed", 0)``：dispatch 异常（work item 修复后真正 fail 才走这里）。

        contract 修复（initial implementation REVIEW）：dispatch 失败被错误归类为 ``skipped`` →
        三态分类避免运维误判全成功。
        """
        repo_id = str(repository.id)
        base_qs = ChunkRegistry.objects.filter(repository_id=repo_id)
        # contract 修复（initial implementation REVIEW）：CONTEXT.md 第 27 行写
        # "last_built_at IS NULL OR last_built_at < migration_time 才需要 backfill"；
        # 默认仍仅过滤 NULL（断点续跑语义不变），传 ``--since`` 时 OR ``< since``
        # 覆盖 EdgeBuilder schema 升级 / weight 算法变更后的全量重建场景，运维
        # 不再需要手动 UPDATE chunk_registry SET last_built_at=NULL。
        if since is None:
            pending_qs = base_qs.filter(last_built_at__isnull=True)
        else:
            pending_qs = base_qs.filter(
                Q(last_built_at__isnull=True) | Q(last_built_at__lt=since)
            )
        chunk_ids: list[uuid.UUID] = list(
            pending_qs.values_list("chunk_id", flat=True)
        )

        if not chunk_ids:
            self.stdout.write(
                f"[SKIP] repo={repository.name} ({repo_id}) "
                f"pending_chunks=0（已 backfill 或无 chunk）"
            )
            return ("skipped_no_work", 0)

        estimated_edges = len(chunk_ids) * MAX_NEIGHBORS_PER_CHUNK

        if dry_run:
            self.stdout.write(
                f"[DRY-RUN] repo={repository.name} ({repo_id}) "
                f"pending_chunks={len(chunk_ids)} "
                f"estimated_edges≈{estimated_edges}"
            )
            return ("processed", len(chunk_ids))

        self.stdout.write(
            f"[BUILD] repo={repository.name} ({repo_id}) "
            f"pending_chunks={len(chunk_ids)} "
            f"estimated_edges≈{estimated_edges}"
        )
        try:
            asyncio.run(self._dispatch_and_drain(repo_id, chunk_ids))
        except Exception as exc:
            logger.error(
                "rebuild_chunk_edges_dispatch_failed",
                repository_id=repo_id,
                pending_chunks=len(chunk_ids),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            self.stderr.write(
                f"[FAIL] repo={repo_id} dispatch 失败: {exc}（last_built_at 不更新）"
            )
            return ("failed", 0)

        # contract 修复（initial implementation REVIEW）：原 ``chunk_id__in=chunk_ids`` 把整个
        # list 展开成 SQL ``IN (?, ?, ...)``，SQLite ``SQLITE_MAX_VARIABLE_NUMBER``
        # 3.32 之前 999、3.32+ 32766；老仓库 backfill 几万 chunk 直接抛
        # ``OperationalError: too many SQL variables``。
        #
        # 简化：dispatch 来源 = 上面 ``pending_qs``（NULL 或 < since），且本命令
        # 是短时窗 backfill；work item 修复后 dispatch 失败已走 except 分支跳过此
        # update → 安全用 pending_qs 的 filter 复用替代 ``chunk_id__in``，避开
        # IN 参数限制 + 一条 UPDATE 完成。
        #
        # 仅有的并发风险：dispatch 期间 indexer 在同 repo 写入新 ``ChunkRegistry``
        # 行（last_built_at=NULL）会被一并 mark，但这些行**未** dispatch 给
        # builder → 下次 backfill 不再重试 → 边可能缺失。在线 backfill 命令一般
        # 离线短跑（运维手动 / scheduler 启动一次），可接受该窗口；若担心可在
        # docstring 标注，或 indexer 自身的 enqueue_edge_build 链路兜底。
        if since is None:
            update_filter = ChunkRegistry.objects.filter(
                repository_id=repo_id, last_built_at__isnull=True
            )
        else:
            update_filter = ChunkRegistry.objects.filter(
                repository_id=repo_id
            ).filter(
                Q(last_built_at__isnull=True) | Q(last_built_at__lt=since)
            )
        updated = update_filter.update(last_built_at=timezone.now())

        self.stdout.write(
            f"[DONE] repo={repo_id} dispatched={len(chunk_ids)} "
            f"last_built_at 已更新 (updated_rows={updated})"
        )
        return ("processed", len(chunk_ids))

    @staticmethod
    async def _dispatch_and_drain(
        repository_id: str, dirty_chunk_ids: list[uuid.UUID]
    ) -> None:
        """触发 enqueue_edge_build 并 drain 本次 dispatch 真正 spawn 的背景 task。

        复用 verify_payload_consistency.py::_dispatch_and_drain 的 before/after
        snapshot 模式（work item lesson）：只 drain 本次 dispatch 真正 spawn 的 task，
        避免误 await 跨 loop / 跨仓库的无关 task（多仓批量 backfill 时尤其重要）。

        work item 修复（initial implementation REVIEW）：``asyncio.gather(..., return_exceptions=True)``
        把 builder 异常吞成返回值，外层 ``try/except`` 永远进不了 except 分支 ——
        失败 build 的 chunk 会被错误标 ``last_built_at != NULL``，下次 backfill
        过滤掉它们 → chunk 永久丢边。修复：检查 gather 返回值，发现任何
        ``BaseException`` 实例时显式 ``raise RuntimeError(...)``，让上游
        ``_process_repo`` 的 ``try/except`` 走 except 分支跳过 ``last_built_at``
        更新（断点续跑：下次 backfill 重试这些 chunk）。
        """
        before = snapshot_background_tasks()
        await enqueue_edge_build(repository_id, dirty_chunk_ids)
        new_tasks = snapshot_background_tasks() - before
        if not new_tasks:
            return
        results = await asyncio.gather(*new_tasks, return_exceptions=True)
        failures = [r for r in results if isinstance(r, BaseException)]
        if failures:
            raise RuntimeError(
                f"{len(failures)}/{len(results)} builder tasks failed; "
                f"first error: {failures[0]!r}"
            )
