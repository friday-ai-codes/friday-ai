"""LearningCase 写入与检索 service（work item RAG）。

自 v0.17.0（Phase 100 / KNOW-02）起，``search_learning_cases`` 底层为统一向量检索：
``DeliveryKnowledgeSearchService.search_similar(entity_kinds=["learning_case"])`` 命中后
按 entity ``source_id`` 回捞 ``McpLearningCase`` 行渲染既有 ``learning_case_payload`` 外形。
旧 token 命中计数实现已退役删除（无 fallback 开关，golden set 对照测试作为验收门兜底）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from interactions.models import InteractionRun
from knowledge.retrieval import DeliveryKnowledgeSearchService
from mcp_tools.models import (
    McpLearningCase,
    McpWorkItemRepoTask,
    McpWorkItemTechnicalPlan,
)

logger = structlog.get_logger(__name__)


class LearningCaseError(Exception):
    """Recoverable learning-case service error."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class LearningCaseResult:
    artifact: McpLearningCase
    output: dict[str, Any]
    traces: list[tuple[str, dict[str, Any]]]


def learning_case_payload(case: McpLearningCase, *, score: float | None = None) -> dict[str, Any]:
    payload = {
        "case_id": str(case.id),
        "title": case.title,
        "work_item_type": case.work_item_type,
        "work_item_id": case.work_item_id,
        "problem": case.problem,
        "root_cause": case.root_cause,
        "solution": case.solution,
        "outcome": case.outcome,
        "repositories": case.repositories,
        "files": case.files,
        "symbols": case.symbols,
        "branches": case.branches,
        "mr_urls": case.mr_urls,
        "tests": case.tests,
        "source_links": case.source_links,
        "reuse_judgement": "可作为相似案例参考，执行前需对比当前代码和需求差异。",
        "created_at": case.created_at.isoformat() if case.created_at else "",
    }
    if score is not None:
        payload["score"] = round(score, 4)
    return payload


async def _resolve_technical_plan(technical_plan_id: str) -> McpWorkItemTechnicalPlan:
    technical_plan = (
        await McpWorkItemTechnicalPlan.objects.select_related("context", "space")
        .filter(id=technical_plan_id)
        .afirst()
    )
    if technical_plan is None:
        raise LearningCaseError("technical_plan_not_found", "技术方案不存在")
    return technical_plan


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


async def create_learning_case_from_technical_plan(
    *,
    run: InteractionRun,
    technical_plan_id: str,
    outcome: str,
    root_cause: str,
    solution_notes: str,
    tests: list[str],
) -> LearningCaseResult:
    """写库成功后经 aschedule_ingestion 投递统一知识摄取（KNOW-01，INV-6 唯一通路）。"""
    technical_plan = await _resolve_technical_plan(technical_plan_id)
    context = technical_plan.context
    tasks = [
        task
        async for task in McpWorkItemRepoTask.objects.select_related("repository")
        .filter(technical_plan=technical_plan)
        .order_by("order")
    ]
    matrix = (
        technical_plan.repository_tasks if isinstance(technical_plan.repository_tasks, list) else []
    )
    repositories = _unique([task.repository.name for task in tasks])
    files = _unique(
        [
            str(path)
            for item in matrix
            if isinstance(item, dict)
            for path in list(item.get("candidate_files") or [])
        ]
    )
    branches = _unique([task.branch_name for task in tasks])
    mr_urls = _unique([task.mr_url for task in tasks])
    task_tests = _unique(
        [
            str(test)
            for item in matrix
            if isinstance(item, dict)
            for test in list(item.get("test_strategy") or [])
        ]
    )
    all_tests = _unique([*tests, *task_tests])
    solution = solution_notes.strip() or "\n".join(
        str(item.get("change_goal") or "") for item in matrix if isinstance(item, dict)
    )
    source_links = {
        "context_id": str(context.id) if context else "",
        "technical_plan_id": str(technical_plan.id),
        "technical_plan_doc_url": technical_plan.feishu_document_url,
        "repo_tasks": [
            {
                "task_id": str(task.id),
                "execution_id": str(task.execution_trace_id or ""),
                "mr_url": task.mr_url,
                "status": task.status,
            }
            for task in tasks
        ],
    }
    problem = (context.description if context else "") or technical_plan.title
    title = technical_plan.title or (context.name if context else "LearningCase")
    case_body = {
        "title": title,
        "problem": problem,
        "root_cause": root_cause,
        "solution": solution,
        "outcome": outcome,
        "repositories": repositories,
        "files": files,
        "branches": branches,
        "mr_urls": mr_urls,
        "tests": all_tests,
        "source_links": source_links,
    }
    embedding_text = "\n".join(
        [
            title,
            problem,
            root_cause,
            solution,
            outcome,
            " ".join(repositories),
            " ".join(files),
            " ".join(branches),
            " ".join(mr_urls),
            " ".join(all_tests),
        ]
    )
    artifact = await McpLearningCase.objects.acreate(
        run=run,
        context=context,
        technical_plan=technical_plan,
        work_item_type=context.work_item_type if context else technical_plan.work_item_type,
        work_item_id=context.work_item_id if context else technical_plan.work_item_id,
        title=title[:240],
        problem=problem,
        root_cause=root_cause,
        solution=solution,
        outcome=outcome or "unknown",
        repositories=repositories,
        files=files,
        symbols=[],
        branches=branches,
        mr_urls=mr_urls,
        tests=all_tests,
        source_links=source_links,
        case_body=case_body,
        embedding_text=embedding_text,
    )
    from knowledge import ingestion  # lazy import 防循环（technical_plan_service.py 同款）

    # aschedule_ingestion 内建 on_commit 语义 + 异常全吞（永不阻塞主流程）；
    # MCP 链归因经 InteractionRun/ToolCallRecord 留痕，后台摄取记 system，不传 initiated_by_user_id。
    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("learning_case", str(artifact.id), "mcp_learning_case_created")
    )
    output = {
        "learning_case_id": str(artifact.id),
        "case": learning_case_payload(artifact),
        "run_id": str(run.run_id),
    }
    traces = [
        (
            "file",
            {
                "source": "learning_case",
                "case_id": str(artifact.id),
                "technical_plan_id": str(technical_plan.id),
                "work_item_id": artifact.work_item_id,
            },
        )
    ]
    return LearningCaseResult(artifact=artifact, output=output, traces=traces)


def _matches_any(hint: str, values: list[Any] | None) -> bool:
    """子串不区分大小写匹配（沿用旧 token 实现的 hint 匹配语义）。"""
    if not hint:
        return False
    return any(hint.lower() in str(value).lower() for value in values or [])


def _hint_bonus(
    case: McpLearningCase,
    *,
    repo_hints: list[str],
    file_hints: list[str],
    symbol_hints: list[str],
) -> float:
    """结果层 rerank 提权：hint 命中累计 +0.05/条，只影响排序不改显示分。"""
    bonus = 0.0
    for hint in repo_hints:
        if _matches_any(hint, case.repositories):
            bonus += 0.05
    for hint in file_hints:
        if _matches_any(hint, case.files):
            bonus += 0.05
    for hint in symbol_hints:
        if _matches_any(hint, case.symbols):
            bonus += 0.05
    return bonus


async def search_learning_cases(
    *,
    query: str,
    work_item_type: str,
    repo_hints: list[str],
    file_hints: list[str],
    symbol_hints: list[str],
    limit: int,
    user,
) -> list[dict[str, Any]]:
    """统一向量检索版 learning case 搜索（KNOW-02，对外 payload 外形不变）。

    - 查询增强：query + work_item_type + 三类 hint 拼入查询文本（hint 不做摆设）；
      拼装后为空直接返回 []（向量检索无「无查询返回最新」语义，schema 描述已注明）；
    - 检索：``search_similar(entity_kinds=["learning_case"], user=...)``（fail-closed
      权限主体），``top_k`` 超采样（limit*3，下限 10）供 rerank / 行过滤余量；
    - 回捞：命中实体 ``source_id``（McpLearningCase UUID str）批量回捞行；实体命中
      但行已删的跳过（弱引用语义）；``work_item_type`` 非空按行字段 post-filter；
    - rerank：排序键 = ``dto.score + hint bonus``；payload ``score`` = 原始向量融合分
      （0-1 浮点，locked 定版），bonus 只影响排序；
    - fail-soft：检索/回捞任何异常 → warning（脱敏后）+ 返回 []（Qdrant 不可用不 500）。
    """
    started = time.perf_counter()
    logger.info(
        "learning_case_search_started",
        query_len=len(query),
        repo_hint_count=len(repo_hints),
        file_hint_count=len(file_hints),
        symbol_hint_count=len(symbol_hints),
        limit=limit,
        component="mcp_tools",
        category="caller",
    )
    parts = [query, work_item_type, *repo_hints, *file_hints, *symbol_hints]
    query_text = " ".join(part.strip() for part in parts if part and part.strip()).strip()
    results: list[dict[str, Any]] = []
    if not query_text:
        logger.info(
            "learning_case_search_completed",
            result_count=0,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            reason="empty_query",
            component="mcp_tools",
            category="caller",
        )
        return results
    try:
        dtos = await DeliveryKnowledgeSearchService().search_similar(
            query_text,
            user=user,
            top_k=max(limit * 3, 10),
            entity_kinds=["learning_case"],
        )
        case_ids = [dto.entity.source_id for dto in dtos]
        cases_by_id: dict[str, McpLearningCase] = {
            str(case.id): case async for case in McpLearningCase.objects.filter(id__in=case_ids)
        }
        scored: list[tuple[float, float, McpLearningCase]] = []
        for dto in dtos:
            case = cases_by_id.get(dto.entity.source_id)
            if case is None:
                continue  # 实体命中但行已删（弱引用语义）
            if work_item_type and case.work_item_type != work_item_type:
                continue
            bonus = _hint_bonus(
                case,
                repo_hints=repo_hints,
                file_hints=file_hints,
                symbol_hints=symbol_hints,
            )
            scored.append((dto.score + bonus, dto.score, case))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = [
            learning_case_payload(case, score=vector_score)
            for _rank_score, vector_score, case in scored[:limit]
        ]
    except Exception as exc:
        logger.warning(
            "learning_case_search_failed",
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            component="mcp_tools",
            category="caller",
        )
        return []
    logger.info(
        "learning_case_search_completed",
        result_count=len(results),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        component="mcp_tools",
        category="caller",
    )
    return results
