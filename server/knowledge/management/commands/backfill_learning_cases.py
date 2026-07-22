"""``backfill_learning_cases`` 管理命令：存量 learning case + MCP 三类产物回填入图（Phase 100）。

「检索切换三件套」（normalizer 100-02/03 + 本回填 + 读切换 100-04）中的存量防线（PITFALLS P1）：
`search_learning_cases` 切换向量检索当天，若存量 `McpLearningCase` / MCP 产物未入图，检索会全空。
本命令按 source 全量**同步逐条**执行 ``ingest``（不经 ``aschedule_ingestion``）补齐：

- 全部 ``McpLearningCase`` → ``source_kind="learning_case"``；
- 全部 ``McpCodingPlan`` → ``source_kind="mcp_coding_plan"``；
- 全部 ``McpRepositoryAnalysis`` → ``source_kind="mcp_repository_analysis"``；
- 全部 ``McpCodingExecutionTrace`` → ``source_kind="mcp_execution_trace"``。

**必须同步执行（code review HI-02 修复）**：``aschedule_ingestion`` 的执行路径是
``transaction.on_commit`` → ``run_in_background`` → **daemon 线程**上的常驻 event loop——
该模式只在常驻服务进程里成立。本命令是一次性 CLI：``handle()`` 调度完立即返回、
进程退出会直接杀死 daemon 线程，排队/执行中的摄取全部丢失（P1 防线名存实亡）。
故命令内直接 ``await ingest(...)``，逐条 try/except 统计失败数并如实上报。

幂等语义（rebuild_project_context 同款）：命令侧总按 source 全量重摄（重复执行处理集合相同）；
真正的内容幂等由 ingestion 的 ``content_hash`` 短路承担——未变内容是空操作（不重嵌入、不翻版本）。

**绝不删库**：不走删库重建路径，只逐条增量摄取；命令行无触发用户 → system 归因
（前台同步执行，日志沿用命令进程 context，不涉及 ``initiated_by_user_id`` 透传）。

    python manage.py backfill_learning_cases
    python manage.py backfill_learning_cases --only learning_case --only mcp_coding_plan
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from django.core.management.base import BaseCommand

from common.logging import redact_secrets_in_text
from knowledge.ingestion import IngestionRequest, ingest

logger = structlog.get_logger(__name__)

_TRIGGER = "backfill_learning_cases"

_SOURCE_KINDS = (
    "learning_case",
    "mcp_coding_plan",
    "mcp_repository_analysis",
    "mcp_execution_trace",
)

# 进度输出粒度（Claude's Discretion：同步摄取含 embed→持久化→upsert 全链，逐百条报进度）
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
) -> tuple[dict[str, int], dict[str, int]]:
    """按 source_kind 全量同步逐条摄取（幂等，不删库）。

    单条失败不中断：warning（脱敏后异常文本）+ 计入 failed，继续下一条。

    Returns:
        (ingested, failed)：按类成功 / 失败计数两个 dict。
    """
    selected = list(only) if only else list(_SOURCE_KINDS)
    ingested: dict[str, int] = {kind: 0 for kind in selected}
    failed: dict[str, int] = {kind: 0 for kind in selected}
    querysets = _querysets()
    total = 0
    for source_kind in selected:
        async for row in querysets[source_kind].aiterator():
            try:
                await ingest(
                    IngestionRequest(
                        source_kind=source_kind,
                        source_id=str(row.id),
                        trigger=_TRIGGER,
                    )
                )
            except Exception as exc:
                # 异常文本脱敏后入日志（观测规范：上游响应/异常文本不可明文留痕）
                logger.warning(
                    "backfill_ingest_failed",
                    source_kind=source_kind,
                    source_id=str(row.id),
                    error=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component="knowledge",
                    category="caller",
                )
                failed[source_kind] += 1
            else:
                ingested[source_kind] += 1
            total += 1
            if on_progress is not None and total % _PROGRESS_EVERY == 0:
                on_progress(total)
    return ingested, failed


class Command(BaseCommand):
    """存量 learning case + MCP 三类产物回填（幂等，绝不删 delivery_knowledge 其他来源）。"""

    help = (
        "存量知识回填：命令内同步逐条摄取全部 McpLearningCase / McpCodingPlan / "
        "McpRepositoryAnalysis / McpCodingExecutionTrace"
        "（content_hash 幂等短路，未变内容空操作；单条失败计数不中断）；"
        "避免检索切换当天全空（P1 防线）。"
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
        ingested, failed = asyncio.run(
            _backfill(
                only,
                on_progress=lambda total: self.stdout.write(f"已处理 {total} 条 ..."),
            )
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        ingested_total = sum(ingested.values())
        failed_total = sum(failed.values())
        logger.info(
            "backfill_learning_cases_completed",
            ingested=ingested,
            ingested_total=ingested_total,
            failed=failed,
            failed_total=failed_total,
            duration_ms=duration_ms,
            component="knowledge",
            category="caller",
        )
        detail = "，".join(
            f"{kind}={count}" + (f"（失败 {failed[kind]}）" if failed[kind] else "")
            for kind, count in ingested.items()
        )
        message = (
            f"存量知识回填已摄取 {ingested_total} 条、失败 {failed_total} 条（{detail}）；"
            f"content_hash 短路保证未变内容幂等空操作，绝不删 delivery_knowledge。"
        )
        if failed_total:
            self.stdout.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(message))
