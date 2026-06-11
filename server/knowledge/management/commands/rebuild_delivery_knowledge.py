"""`rebuild_delivery_knowledge` 管理命令：显式删除并重建 delivery_knowledge collection。

唯一合法的重建入口（P8 灾难防线的另一半）：
``ensure_delivery_knowledge_collection`` 在配置不匹配时只会响亮拒绝，
任何删库重建动作必须经本命令显式 ``--yes`` 确认。

    python manage.py rebuild_delivery_knowledge          # 仅打印警告，不动数据
    python manage.py rebuild_delivery_knowledge --yes    # 删除 → 重建 → 元信息更新

TODO(Phase 13)：接入摄取管线后本命令需扩展"从 PG（KnowledgeEntityVersion.content）
全量重嵌入"步骤；当前阶段 collection 尚无数据，重建 = 删 + 建即可。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandParser

from knowledge.collection import (
    DELIVERY_KNOWLEDGE_COLLECTION,
    ensure_delivery_knowledge_collection,
    get_expected_dimension,
)
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
            self.stdout.write("  并更新 SystemSetting `knowledge_collection_meta` 元信息。")
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
        dimension = asyncio.run(self._rebuild())
        logger.info(
            "rebuild_delivery_knowledge_finished",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            dimension=dimension,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"collection `{DELIVERY_KNOWLEDGE_COLLECTION}` 已重建"
                f"（dense 维度 {dimension}，hybrid + 全部 payload index，元信息已更新）"
            )
        )

    @staticmethod
    async def _rebuild() -> int:
        """删除 → 经 ensure 重建（创建 + payload index + 元信息更新都在 ensure 内完成）。

        任何异常不吞——自然冒泡为非零退出码。返回重建后的 dense 维度（醒目输出用）。
        """
        await sync_to_async(QdrantService.delete_collection_by_name)(DELIVERY_KNOWLEDGE_COLLECTION)
        await ensure_delivery_knowledge_collection()
        return await get_expected_dimension()
