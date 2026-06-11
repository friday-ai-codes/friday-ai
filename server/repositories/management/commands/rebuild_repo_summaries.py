"""`rebuild_repo_summaries` 管理命令 —— 仓库路由索引（repo_summaries）存量回填。

仓库摘要索引只在索引收尾（FINALIZING）阶段构建，且失败只记 warning 不影响
INDEXED 终态。因此存在两类"代码索引正常但 route_repositories 返回空"的仓库：

1. 在 repo_summaries 功能上线之前完成索引的老仓库；
2. 收尾时摘要构建失败（embedding / sparse 编码异常）的仓库。

本命令对这些仓库批量重建摘要，无需重跑完整索引：

    python manage.py rebuild_repo_summaries                 # 全部 INDEXED 仓库
    python manage.py rebuild_repo_summaries --repo <uuid>   # 指定仓库（可重复）

幂等：RepoSummaryBuilder.build 内部按 repository_id 做确定性 point id upsert，
重复执行只会覆盖同一条摘要。
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser

from repositories.models import IndexStatus, Repository

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """批量重建 Qdrant repo_summaries 摘要索引（仓库路由依赖）。"""

    help = (
        "Rebuild the repo_summaries routing index for indexed repositories; "
        "fixes empty route_repositories results without re-indexing"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--repo",
            action="append",
            dest="repos",
            default=None,
            help="仓库 UUID，可重复指定；缺省时处理所有 INDEXED 仓库",
        )

    def handle(self, *args: object, **options: object) -> None:
        repos: list[str] | None = options.get("repos")  # type: ignore[assignment]

        if repos:
            for raw in repos:
                try:
                    uuid.UUID(raw)
                except ValueError as exc:
                    raise CommandError(f"无效的仓库 UUID: {raw}") from exc
            queryset = Repository.objects.filter(id__in=repos)
        else:
            queryset = Repository.objects.filter(index_status=IndexStatus.INDEXED)

        targets = list(queryset.values_list("id", "name"))
        if not targets:
            self.stdout.write(self.style.WARNING("没有可处理的仓库"))
            return

        results = asyncio.run(self._rebuild_all(targets))

        ok = sum(1 for success in results.values() if success)
        failed = [str(repo_id) for repo_id, success in results.items() if not success]
        self.stdout.write(self.style.SUCCESS(f"repo_summaries 重建完成: {ok}/{len(targets)} 成功"))
        if failed:
            self.stdout.write(
                self.style.ERROR(
                    "失败仓库（详见日志 repo_summary_build_failed）: " + ", ".join(failed)
                )
            )

    async def _rebuild_all(self, targets: list[tuple[uuid.UUID, str]]) -> dict[uuid.UUID, bool]:
        from codegraph.services.repo_summary_builder import RepoSummaryBuilder

        results: dict[uuid.UUID, bool] = {}
        # 串行执行：embedding 服务和 Qdrant 写入都不需要并发压力
        for repo_id, name in targets:
            self.stdout.write(f"rebuilding {name} ({repo_id}) ...")
            try:
                results[repo_id] = await RepoSummaryBuilder.build(repository_id=str(repo_id))
            except Exception:
                logger.warning(
                    "repo_summary_build_failed",
                    repository_id=str(repo_id),
                    exc_info=True,
                )
                results[repo_id] = False
        return results
