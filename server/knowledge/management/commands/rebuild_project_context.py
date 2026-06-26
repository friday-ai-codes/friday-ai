"""``rebuild_project_context`` 管理命令：项目上下文物化兜底全量重建（CTX-01/02）。

「写时增量 + 兜底定时全量重建 + content_hash 幂等短路」三者合成的跨重启安全网（85-01）：
写时钩子若在投递后、摄取完成前进程重启而丢任务，本命令按 source 重新 ``aschedule_ingestion``
补齐缺失/漂移的向量；``content_hash`` 短路保证对未变内容是**幂等空操作**（不重嵌入、不翻版本）。

遍历范围：
- 全部 ``ProjectDoc``（5 文件容器）→ ``aschedule_ingestion(source_kind="project_doc")``；
- 全部 **active** ``ProjectMemory`` → ``aschedule_ingestion(source_kind="project_memory")``。

**绝不删库**：不走删库重建路径（那条危险命令会清空整个 delivery_knowledge collection，连带
抹掉 work_item/tech_plan/code_change 等其他来源），本命令只按项目上下文两类来源重新调度增量
摄取（A5）。定时任务无触发用户 → system 归因（``aschedule_ingestion`` 不传
``initiated_by_user_id``）。

    python manage.py rebuild_project_context
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from django.core.management.base import BaseCommand

from knowledge.ingestion import IngestionRequest, aschedule_ingestion

logger = structlog.get_logger(__name__)


async def _rebuild_project_context() -> int:
    """按 source 重新调度项目上下文摄取（幂等，不删库）。返回调度条数。"""
    from initiatives.models import ProjectDoc, ProjectMemory, ProjectMemoryStatus

    scheduled = 0

    async for doc in ProjectDoc.objects.all().aiterator():
        await aschedule_ingestion(
            IngestionRequest(
                source_kind="project_doc",
                source_id=str(doc.id),
                trigger="rebuild_project_context",
            )
        )
        scheduled += 1

    async for memory in (
        ProjectMemory.objects.filter(status=ProjectMemoryStatus.ACTIVE).aiterator()
    ):
        await aschedule_ingestion(
            IngestionRequest(
                source_kind="project_memory",
                source_id=str(memory.id),
                trigger="rebuild_project_context",
            )
        )
        scheduled += 1

    return scheduled


class Command(BaseCommand):
    """项目上下文物化兜底全量重建（幂等，绝不删 delivery_knowledge 其他来源）。"""

    help = (
        "项目上下文物化兜底全量重建：按 source 重新调度全部 ProjectDoc + active ProjectMemory "
        "的增量摄取（content_hash 幂等短路，未变内容空操作）；绝不删 delivery_knowledge collection。"
    )

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.perf_counter()
        logger.info(
            "rebuild_project_context_started",
            component="knowledge",
            category="caller",
        )
        scheduled = asyncio.run(_rebuild_project_context())
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "rebuild_project_context_completed",
            scheduled=scheduled,
            duration_ms=duration_ms,
            component="knowledge",
            category="caller",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"项目上下文兜底重建已调度 {scheduled} 条（project_doc + active project_memory）；"
                f"content_hash 短路保证未变内容幂等空操作。"
            )
        )
