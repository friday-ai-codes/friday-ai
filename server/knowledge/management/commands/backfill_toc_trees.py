"""`backfill_toc_trees` 管理命令 —— 存量知识版本章节树回填（PageIndex 化）。

toc_tree 在摄取路径生成；本命令对功能上线前已落库的 latest 版本批量补建：

    python manage.py backfill_toc_trees            # 全部 toc_tree 为空的 latest 版本
    python manage.py backfill_toc_trees --limit 500

纯确定性计算（chunk_knowledge_text + build_toc_tree），零 LLM、零向量写入，
可安全重复执行。
"""

from __future__ import annotations

import structlog
from django.core.management.base import BaseCommand, CommandParser

from knowledge.chunking import chunk_knowledge_text
from knowledge.models import KnowledgeEntityVersion
from knowledge.toc_tree import build_toc_tree

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    """批量回填 KnowledgeEntityVersion.toc_tree。"""

    help = "Backfill toc_tree for existing latest knowledge entity versions"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=1000,
            help="本批最多处理的版本数（默认 1000）",
        )

    def handle(self, *args: object, **options: object) -> None:
        limit: int = int(options.get("limit") or 1000)

        queryset = (
            KnowledgeEntityVersion.objects.select_related("entity")
            .filter(is_latest=True, toc_tree=[])
            .order_by("created_at")[:limit]
        )

        built = 0
        empty = 0
        for version in queryset.iterator():
            chunks = chunk_knowledge_text(version.entity.title, version.content)
            toc_tree = build_toc_tree(
                version.entity.title, version.content, [c.text for c in chunks]
            )
            if not toc_tree:
                empty += 1
                continue
            version.toc_tree = toc_tree
            version.save(update_fields=["toc_tree"])
            built += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"toc_tree 回填完成: built={built}, no_headings={empty}"
            )
        )
