"""reconcile 仓库索引进度计数器与实际存储（Qdrant / FileIndex）的失同步。

背景（2026-08）：索引进度在触发时被清零（``IndexTriggerView`` / ``index_enqueue`` /
``reindex-all`` 三处），完成时经 ``update_index_progress`` 回写。若索引中断、或收尾
回写未覆盖某字段，``indexed_files_total`` / ``index_total_chunks`` 会停在 0 或偏小值，
而 Qdrant 向量与 FileIndex 锚点早已写入 —— DB 显示"未索引/只索引 2 文件"，实际数据完好。

口径与安全（绝不把对的改错）：
- **只修欠报，只上调不下调**。DB 计数 < 实际下界才回写；DB 已 >= 下界视为正常，不动。
- ``indexed_files_total`` 下界取 ``max(Qdrant base 分支 distinct file 数, FileIndex 锚点数)``
  的**保守最小可信值**——用 FileIndex 行数（当前轮锚点）作主，避免 Qdrant 跨分支累积高估。
- ``index_total_chunks`` 下界取 Qdrant ``points_count`` 与现有值的关系同理只上调。
- 绝不动 index_status / last_indexed_commit_sha / 向量 / FileIndex 锚点。

用法:
    python manage.py reconcile_index_counters                  # 修复所有欠报仓
    python manage.py reconcile_index_counters --repo-id UUID   # 只修指定仓
    python manage.py reconcile_index_counters --dry-run        # 仅报告，不写
"""

from __future__ import annotations

from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandParser

from repositories.models import FileIndex, Repository
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

_COMPONENT = "reconcile_index_counters"


class Command(BaseCommand):
    help = "以实际存储为权威，只上调失同步（欠报）的 indexed_files_total / index_total_chunks"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--repo-id", type=str, default=None, help="只修指定仓库 (UUID)")
        parser.add_argument("--dry-run", action="store_true", help="仅报告失同步，不写库")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        repo_id: str | None = options["repo_id"]

        qs = Repository.objects.filter(is_deleted=False)
        if repo_id:
            qs = qs.filter(id=repo_id)

        repos = list(qs.order_by("name"))
        self.stdout.write(f"扫描 {len(repos)} 个未删除仓库…")

        drifted = 0
        fixed = 0
        no_collection = 0
        for repo in repos:
            # FileIndex 锚点数 = 当前轮已索引文件数的 DB 内下界（快，不碰 Qdrant）。
            file_index_count = FileIndex.objects.filter(repository_id=repo.id).count()

            db_files = int(repo.indexed_files_total or 0)
            db_chunks = int(repo.index_total_chunks or 0)

            # 仅在 DB 文件计数明显欠报（低于 FileIndex 锚点）时才需要查 Qdrant 补 chunks。
            if db_files >= file_index_count and file_index_count > 0:
                continue  # DB 不欠报，跳过（避免 Qdrant 跨分支累积高估）

            stats = QdrantService.get_collection_stats(str(repo.id))
            if not stats.get("exists"):
                no_collection += 1
                continue
            qdrant_chunks = int(stats.get("points_count") or 0)

            # 目标值：文件数取 FileIndex 锚点（当前轮下界），chunks 取 max(db, qdrant)。
            target_files = max(db_files, file_index_count)
            target_chunks = max(db_chunks, qdrant_chunks)

            if target_files == db_files and target_chunks == db_chunks:
                continue
            drifted += 1

            logger.info(
                "index_counter_drift_detected",
                repository_id=str(repo.id),
                repository=repo.name,
                db_files=db_files,
                file_index_anchors=file_index_count,
                db_chunks=db_chunks,
                qdrant_chunks=qdrant_chunks,
                target_files=target_files,
                target_chunks=target_chunks,
                component=_COMPONENT,
                category="caller",
            )
            self.stdout.write(
                f"  {repo.name}: files {db_files}→{target_files}"
                f" (FileIndex={file_index_count}), chunks {db_chunks}→{target_chunks}"
            )

            if dry_run:
                continue

            repo.indexed_files_total = target_files
            repo.indexed_files_processed = target_files
            repo.index_total_chunks = target_chunks
            repo.index_processed_chunks = target_chunks
            repo.save(
                update_fields=[
                    "indexed_files_total",
                    "indexed_files_processed",
                    "index_total_chunks",
                    "index_processed_chunks",
                ]
            )
            fixed += 1

        summary = (
            f"完成：扫描 {len(repos)}，欠报失同步 {drifted}，"
            f"{'(dry-run) 待修' if dry_run else '已修'} {drifted if dry_run else fixed}，"
            f"无 collection 跳过 {no_collection}"
        )
        logger.info(
            "index_counter_reconcile_completed",
            scanned=len(repos),
            drifted=drifted,
            fixed=(drifted if dry_run else fixed),
            dry_run=dry_run,
            skipped_no_collection=no_collection,
            component=_COMPONENT,
            category="caller",
        )
        self.stdout.write(self.style.SUCCESS(summary))
