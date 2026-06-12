"""`backfill_repo_trees` 管理命令 —— 存量仓库能力树回填（PageIndex 化）。

对尚无 ai_summary_tree 的仓库批量 dispatch repo_summary 容器任务（claude code
读码生成能力树）。任务实际执行在 Runner 容器内，本命令只负责派发：

    python manage.py backfill_repo_trees                  # 全部 INDEXED 且无树的仓库
    python manage.py backfill_repo_trees --limit 20       # 限制本批派发数（成本控制）
    python manage.py backfill_repo_trees --repo <uuid>    # 指定仓库（可重复，强制重建）
    python manage.py backfill_repo_trees --revectorize    # 不派发任务，仅对已有树的仓库
                                                          # 重建 repo_index_nodes 节点向量

派发防重入：ai_summary_status 为 pending/running 的仓库自动跳过。
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser

from repositories.models import AISummaryStatus, IndexStatus, Repository

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """批量回填仓库能力树（dispatch repo_summary）或重建节点向量。"""

    help = "Backfill PageIndex capability trees for existing repositories"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--repo",
            action="append",
            dest="repos",
            default=None,
            help="仓库 UUID，可重复指定（强制重建，无视已有树）",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="本批最多派发的任务数（默认 50，成本控制）",
        )
        parser.add_argument(
            "--revectorize",
            action="store_true",
            help="仅对已有树的仓库重建 repo_index_nodes 节点向量（零 LLM）",
        )

    def handle(self, *args: object, **options: object) -> None:
        repos: list[str] | None = options.get("repos")  # type: ignore[assignment]
        limit: int = int(options.get("limit") or 50)
        revectorize: bool = bool(options.get("revectorize"))

        if repos:
            for raw in repos:
                try:
                    uuid.UUID(raw)
                except ValueError as exc:
                    raise CommandError(f"无效的仓库 UUID: {raw}") from exc

        if revectorize:
            asyncio.run(self._revectorize_all(repos))
            return

        asyncio.run(self._dispatch_all(repos, limit))

    async def _dispatch_all(self, repos: list[str] | None, limit: int) -> None:
        from repositories.summary_service import dispatch_repo_summary

        if repos:
            queryset = Repository.objects.filter(id__in=repos, is_deleted=False)
        else:
            queryset = Repository.objects.filter(
                is_deleted=False,
                index_status=IndexStatus.INDEXED,
                ai_summary_tree__isnull=True,
            )

        dispatched = 0
        skipped = 0
        async for repo in queryset:
            if dispatched >= limit:
                break
            if repo.ai_summary_status in (
                AISummaryStatus.PENDING,
                AISummaryStatus.RUNNING,
            ):
                skipped += 1
                continue
            try:
                session_id = await dispatch_repo_summary(repo)
                dispatched += 1
                self.stdout.write(f"dispatched {repo.name} → {session_id}")
            except Exception:
                logger.warning(
                    "backfill_repo_tree_dispatch_failed",
                    repository_id=str(repo.id),
                    exc_info=True,
                )
                self.stdout.write(
                    self.style.ERROR(f"dispatch failed: {repo.name} ({repo.id})")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"能力树回填派发完成: dispatched={dispatched}, skipped_inflight={skipped}"
            )
        )

    async def _revectorize_all(self, repos: list[str] | None) -> None:
        from codegraph.services.repo_index_tree import RepoIndexTreeBuilder

        if repos:
            queryset = Repository.objects.filter(id__in=repos, is_deleted=False)
        else:
            queryset = Repository.objects.filter(
                is_deleted=False, ai_summary_tree__isnull=False
            )

        ok = 0
        failed = 0
        async for repo in queryset:
            if not repo.ai_summary_tree:
                continue
            self.stdout.write(f"revectorizing {repo.name} ({repo.id}) ...")
            success = await RepoIndexTreeBuilder.build(str(repo.id))
            if success:
                ok += 1
            else:
                failed += 1
        self.stdout.write(
            self.style.SUCCESS(f"节点向量重建完成: ok={ok}, failed={failed}")
        )
