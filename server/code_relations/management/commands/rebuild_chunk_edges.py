"""Phase Plan Task 2：`rebuild_chunk_edges` 管理命令。
老仓库（v23.0 索引完无 ChunkEdge）批量 backfill 入口：
 python manage.py rebuild_chunk_edges --repo <uuid> # 单仓库
 python manage.py rebuild_chunk_edges --all # 全 INDEXED 仓库
 python manage.py rebuild_chunk_edges --repo <uuid> --dry-run # 预估不写入
**断点续跑语义：** 仅 dispatch `ChunkRegistry.last_built_at IS NULL` 的 chunk，
命令完成后 `update(last_built_at=now)` 标记 per row；二次跑跳过已建 chunk。
**复用策略：** 命令本身不重新实现 builder 调度，直接调用 Phase
`code_relations.tasks.enqueue_edge_build`；fire-and-forget 任务由 `_dispatch_and_drain`
helper 复用 `verify_payload_consistency.py` 的 before/after snapshot 模式确保
真正完成再 update last_built_at。
**并发度（CONTEXT / ）：** 默认串行单 repo 跑（避免多 repo × 6 builder 同
时跑爆 RAM）；未来扩展 `--concurrency N` 参数预留接口（本 plan 不实现）。
引用：
- ROADMAP /
- Phase CONTEXT （backfill 触发点）/ （复用 enqueue_edge_build）
- verify_payload_consistency.py（BaseCommand + asyncio.run + drain 模式样板）
"""
from __future__ import annotations
import asyncio
import uuid
from typing import Any
import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import QuerySet
from django.utils import timezone
from code_relations import tasks as tasks_module
from code_relations.constants import MAX_NEIGHBORS_PER_CHUNK
from code_relations.models import ChunkRegistry
from code_relations.tasks import enqueue_edge_build
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
 def handle(self, *args: Any, **options: Any) -> None:
 repo_filter: str | None = options["repo"]
 all_mode: bool = options["all"]
 dry_run: bool = options["dry_run"]
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
 skipped_repos = 0
 total_chunks_dispatched = 0
 for repo in repos:
 dispatched = self._process_repo(repo, dry_run=dry_run)
 if dispatched > 0:
 processed_repos += 1
 total_chunks_dispatched += dispatched
 else:
 skipped_repos += 1
 self.stdout.write("")
 self.stdout.write(
 f"Summary: processed_repos={processed_repos} "
 f"skipped_repos={skipped_repos} "
 f"total_chunks_dispatched={total_chunks_dispatched} "
 f"dry_run={dry_run}"
 )
 logger.info(
 "rebuild_chunk_edges_finished",
 processed_repos=processed_repos,
 skipped_repos=skipped_repos,
 total_chunks_dispatched=total_chunks_dispatched,
 dry_run=dry_run,
 )
 def _process_repo(self, repository: Repository, *, dry_run: bool) -> int:
 """处理单个 repo：选 pending chunks → dispatch（或 dry-run 预估）→ 更新 last_built_at。
 Returns:
 实际 dispatch（或 dry-run 预估）的 chunk 数；0 表示跳过（无 pending）。
 """
 repo_id = str(repository.id)
 chunk_ids: list[uuid.UUID] = list(
 ChunkRegistry.objects.filter(
 repository_id=repo_id, last_built_at__isnull=True
 ).values_list("chunk_id", flat=True)
 )
 if not chunk_ids:
 self.stdout.write(
 f"[SKIP] repo={repository.name} ({repo_id}) "
 f"pending_chunks=0（已 backfill 或无 chunk）"
 )
 return 0
 estimated_edges = len(chunk_ids) * MAX_NEIGHBORS_PER_CHUNK
 if dry_run:
 self.stdout.write(
 f"[DRY-RUN] repo={repository.name} ({repo_id}) "
 f"pending_chunks={len(chunk_ids)} "
 f"estimated_edges≈{estimated_edges}"
 )
 return len(chunk_ids)
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
 return 0
 ChunkRegistry.objects.filter(
 repository_id=repo_id, chunk_id__in=chunk_ids
 ).update(last_built_at=timezone.now)
 self.stdout.write(
 f"[DONE] repo={repo_id} dispatched={len(chunk_ids)} "
 f"last_built_at 已更新"
 )
 return len(chunk_ids)
 @staticmethod
 async def _dispatch_and_drain(
 repository_id: str, dirty_chunk_ids: list[uuid.UUID]
 ) -> None:
 """触发 enqueue_edge_build 并 drain 本次 dispatch 真正 spawn 的背景 task。
 复用 verify_payload_consistency.py:_dispatch_and_drain 的 before/after
 snapshot 模式（ lesson）：只 drain 本次 dispatch 真正 spawn 的 task，
 避免误 await 跨 loop / 跨仓库的无关 task（多仓批量 backfill 时尤其重要）。
 修复（Phase REVIEW）：``asyncio.gather(..., return_exceptions=True)``
 把 builder 异常吞成返回值，外层 ``try/except`` 永远进不了 except 分支 ——
 失败 build 的 chunk 会被错误标 ``last_built_at != NULL``，下次 backfill
 过滤掉它们 → chunk 永久丢边。修复：检查 gather 返回值，发现任何
 ``BaseException`` 实例时显式 ``raise RuntimeError(...)``，让上游
 ``_process_repo`` 的 ``try/except`` 走 except 分支跳过 ``last_built_at``
 更新（断点续跑：下次 backfill 重试这些 chunk）。
 """
 before = set(tasks_module._BACKGROUND_TASKS)
 await enqueue_edge_build(repository_id, dirty_chunk_ids)
 new_tasks = tasks_module._BACKGROUND_TASKS - before
 if not new_tasks:
 return
 results = await asyncio.gather(*new_tasks, return_exceptions=True)
 failures = [r for r in results if isinstance(r, BaseException)]
 if failures:
 raise RuntimeError(
 f"{len(failures)}/{len(results)} builder tasks failed; "
 f"first error: {failures[0]!r}"
 )
