"""``backfill_learning_cases`` 管理命令：存量 learning case + MCP 三类产物回填入图（Phase 100）。

「检索切换三件套」（normalizer 100-02/03 + 本回填 + 读切换 100-04）中的存量防线（PITFALLS P1）：
`search_learning_cases` 切换向量检索当天，若存量 `McpLearningCase` / MCP 产物未入图，检索会全空。
本命令按 source 全量重新 ``aschedule_ingestion`` 补齐：

- 全部 ``McpLearningCase`` → ``source_kind="learning_case"``；
- 全部 ``McpCodingPlan`` → ``source_kind="mcp_coding_plan"``；
- 全部 ``McpRepositoryAnalysis`` → ``source_kind="mcp_repository_analysis"``；
- 全部 ``McpCodingExecutionTrace`` → ``source_kind="mcp_execution_trace"``。

幂等语义（rebuild_project_context 同款）：命令侧总按 source 全量重调度（重复执行投递集合相同）；
真正的内容幂等由 ingestion 的 ``content_hash`` 短路承担——未变内容是空操作（不重嵌入、不翻版本）。

**绝不删库**：不走删库重建路径，只重新调度增量摄取；命令行无触发用户 → system 归因
（``aschedule_ingestion`` 不传 ``initiated_by_user_id``）。

    python manage.py backfill_learning_cases
    python manage.py backfill_learning_cases --only learning_case --only mcp_coding_plan
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from django.core.management.base import BaseCommand

from knowledge.ingestion import IngestionRequest, aschedule_ingestion

logger = structlog.get_logger(__name__)

_TRIGGER = "backfill_learning_cases"

_SOURCE_KINDS = (
    "learning_case",
    "mcp_coding_plan",
    "mcp_repository_analysis",
    "mcp_execution_trace",
)

# 进度输出粒度（Claude's Discretion：aschedule_ingestion 只是投递后台队列，轻量，无需批次控制）
_PROGRESS_EVERY = 100


def _querysets() -> dict[str, Any]:
    """source_kind → 全量 queryset 映射（惰性 import，避免 app 加载序问题）。"""
    from mcp_tools.models import (
        McpCodingExecutionTrace,
        McpCodingPlan,
        McpLearningCase,
        McpRepositoryAnalysis,
    )

    return {
        "learning_case": McpLearningCase.objects.all(),
        "mcp_coding_plan": McpCodingPlan.objects.all(),
        "mcp_repository_analysis": McpRepositoryAnalysis.objects.all(),
        "mcp_execution_trace": McpCodingExecutionTrace.objects.all(),
    }


async def _backfill(
    only: list[str] | None = None,
    *,
    on_progress: Any = None,
) -> dict[str, int]:
    """按 source_kind 全量重新调度摄取（幂等，不删库）。返回按类计数 dict。"""
    selected = list(only) if only else list(_SOURCE_KINDS)
    scheduled: dict[str, int] = {kind: 0 for kind in selected}
    querysets = _querysets()
    total = 0
    for source_kind in selected:
        async for row in querysets[source_kind].aiterator():
            await aschedule_ingestion(
                IngestionRequest(
                    source_kind=source_kind,
                    source_id=str(row.id),
                    trigger=_TRIGGER,
                )
            )
            scheduled[source_kind] += 1
            total += 1
            if on_progress is not None and total % _PROGRESS_EVERY == 0:
                on_progress(total)
    return scheduled


class Command(BaseCommand):
    """存量 learning case + MCP 三类产物回填（幂等，绝不删 delivery_knowledge 其他来源）。"""

    help = (
        "存量知识回填：按 source 重新调度全部 McpLearningCase / McpCodingPlan / "
        "McpRepositoryAnalysis / McpCodingExecutionTrace 的增量摄取"
        "（content_hash 幂等短路，未变内容空操作）；避免检索切换当天全空（P1 防线）。"
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--only",
            action="append",
            choices=list(_SOURCE_KINDS),
            default=None,
            help="只回填指定 source_kind（可重复传入），缺省全量四类。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        only = options.get("only")
        started = time.perf_counter()
        logger.info(
            "backfill_learning_cases_started",
            only=only or list(_SOURCE_KINDS),
            component="knowledge",
            category="caller",
        )
        scheduled = asyncio.run(
            _backfill(
                only,
                on_progress=lambda total: self.stdout.write(f"已调度 {total} 条 ..."),
            )
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "backfill_learning_cases_completed",
            scheduled=scheduled,
            scheduled_total=sum(scheduled.values()),
            duration_ms=duration_ms,
            component="knowledge",
            category="caller",
        )
        detail = "，".join(f"{kind}={count}" for kind, count in scheduled.items())
        self.stdout.write(
            self.style.SUCCESS(
                f"存量知识回填已调度 {sum(scheduled.values())} 条（{detail}）；"
                f"content_hash 短路保证未变内容幂等空操作，绝不删 delivery_knowledge。"
            )
        )
