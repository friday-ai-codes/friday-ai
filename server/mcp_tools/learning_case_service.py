"""LearningCase writer and retrieval service for work item RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from interactions.models import InteractionRun
from mcp_tools.models import (
    McpLearningCase,
    McpWorkItemRepoTask,
    McpWorkItemTechnicalPlan,
)


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


_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-/.\u4e00-\u9fff]{2,}")


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value)}


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
    technical_plan = await _resolve_technical_plan(technical_plan_id)
    context = technical_plan.context
    tasks = [
        task
        async for task in McpWorkItemRepoTask.objects.select_related("repository")
        .filter(technical_plan=technical_plan)
        .order_by("order")
    ]
    matrix = technical_plan.repository_tasks if isinstance(technical_plan.repository_tasks, list) else []
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
        str(item.get("change_goal") or "")
        for item in matrix
        if isinstance(item, dict)
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


async def search_learning_cases(
    *,
    query: str,
    work_item_type: str,
    repo_hints: list[str],
    file_hints: list[str],
    symbol_hints: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    query_tokens = _tokens(" ".join([query, *repo_hints, *file_hints, *symbol_hints]))
    candidates = McpLearningCase.objects.all()
    if work_item_type:
        candidates = candidates.filter(work_item_type=work_item_type)
    scored: list[tuple[float, McpLearningCase]] = []
    async for case in candidates.order_by("-created_at")[:200]:
        text = (case.embedding_text or "").lower()
        score = 0.0
        for token in query_tokens:
            if token in text:
                score += 1.0
        for hint in repo_hints:
            if hint and any(hint.lower() in str(repo).lower() for repo in case.repositories or []):
                score += 3.0
        for hint in file_hints:
            if hint and any(hint.lower() in str(path).lower() for path in case.files or []):
                score += 3.0
        for hint in symbol_hints:
            if hint and any(hint.lower() in str(symbol).lower() for symbol in case.symbols or []):
                score += 3.0
        if score > 0 or not query_tokens:
            scored.append((score, case))
    scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    return [learning_case_payload(case, score=score) for score, case in scored[:limit]]
