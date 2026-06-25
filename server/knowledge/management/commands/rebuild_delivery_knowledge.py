"""`rebuild_delivery_knowledge` 管理命令：显式删除并重建 delivery_knowledge collection。

唯一合法的重建入口（P8 灾难防线的另一半）：
``ensure_delivery_knowledge_collection`` 在配置不匹配时只会响亮拒绝，
任何删库重建动作必须经本命令显式 ``--yes`` 确认。

删建之后从 PG 真值全量重嵌入（Plan 13-04，灾备 / 维度变更路径闭环）：
逐个 latest 版本（``is_latest=True``，旧版本不进检索面——P10 分面纪律）
经 ``revectorize_version`` 重走 chunk → embed → upsert；单版本失败
error 记录后继续（重建场景容忍个别坏数据），结束时报告失败计数。

    python manage.py rebuild_delivery_knowledge          # 仅打印警告，不动数据
    python manage.py rebuild_delivery_knowledge --yes    # 删除 → 重建 → 全量重嵌入
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandParser

from knowledge import ingestion
from knowledge.collection import (
    DELIVERY_KNOWLEDGE_COLLECTION,
    ensure_delivery_knowledge_collection,
    get_expected_dimension,
)
from knowledge.models import KnowledgeEntityVersion
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """显式删除并重建 delivery_knowledge collection（危险操作，需 --yes 确认）。"""

    help = (
        "显式删除并重建 delivery_knowledge collection（危险操作）：清空全部知识向量，"
        "按当前 EMBEDDING_DIMENSION 重建空 collection 并更新 SystemSetting 元信息；"
        "必须追加 --yes 确认，否则仅打印警告退出"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--yes",
            action="store_true",
            dest="yes",
            help="确认执行删除并重建（无此参数时仅打印将发生什么，不动任何数据）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["yes"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(self.style.WARNING("  危险操作：重建 delivery_knowledge collection"))
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(
                f"  将删除 collection `{DELIVERY_KNOWLEDGE_COLLECTION}` 的全部向量数据，"
            )
            self.stdout.write(
                "  按当前 EMBEDDING_DIMENSION 重建空 collection（hybrid + payload index），"
            )
            self.stdout.write("  更新 SystemSetting `knowledge_collection_meta` 元信息，")
            self.stdout.write("  并从 PG（KnowledgeEntityVersion latest 版本）全量重嵌入。")
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write("")
            self.stdout.write("  未执行任何操作。确认无误后请追加 --yes 重新运行：")
            self.stdout.write("    python manage.py rebuild_delivery_knowledge --yes")
            self.stdout.write("")
            return

        logger.info(
            "rebuild_delivery_knowledge_started",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
        )
        dimension, reembedded, failed = asyncio.run(self._rebuild())
        logger.info(
            "rebuild_delivery_knowledge_finished",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            dimension=dimension,
            reembedded=reembedded,
            failed=failed,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"collection `{DELIVERY_KNOWLEDGE_COLLECTION}` 已重建"
                f"（dense 维度 {dimension}，hybrid + 全部 payload index，元信息已更新；"
                f"全量重嵌入 reembedded={reembedded} failed={failed}）"
            )
        )
        if failed:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠️  {failed} 个 latest 版本重嵌入失败（详见 "
                    f"knowledge_rebuild_reembed_failed 日志），可经 "
                    f"reconcile_delivery_knowledge --fix 补救"
                )
            )

    @staticmethod
    async def _rebuild() -> tuple[int, int, int]:
        """删除 → 经 ensure 重建 → 从 PG latest 版本全量重嵌入。

        删建异常不吞——自然冒泡为非零退出码；重嵌入阶段单版本失败 error
        记录后继续（重建场景容忍个别坏数据，整体进度不被单点拖垮）。
        返回 (dense 维度, 重嵌入成功数, 失败数)（醒目输出用）。
        """
        await sync_to_async(QdrantService.delete_collection_by_name)(DELIVERY_KNOWLEDGE_COLLECTION)
        await ensure_delivery_knowledge_collection()
        dimension = await get_expected_dimension()

        reembedded = 0
        failed = 0
        # 只过滤 is_latest=True：旧版本不进检索面（P10 分面纪律——
        # 版本链回溯走 PG，召回面只承载 latest）
        qs = KnowledgeEntityVersion.objects.filter(is_latest=True).select_related(
            "entity", "entity__space", "entity__repository"
        )
        async for version in qs.aiterator():
            try:
                await ingestion.revectorize_version(version)
                reembedded += 1
            except Exception as exc:
                failed += 1
                logger.error(
                    "knowledge_rebuild_reembed_failed",
                    version_id=str(version.id),
                    entity_id=str(version.entity_id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        return dimension, reembedded, failed
