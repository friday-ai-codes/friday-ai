"""LOOP-04 平台 Skill 步骤工具 handler 薄封装（v0.17.0 Phase 101 / 101-04）。

`pre_coding_research` / `post_coding_capture` 两个平台 Skill 的 7 个步骤工具的
builtin handler。**只做参数适配 + 结果 JSON 化，逻辑全部委托既有 service**，
零重复实现：

- ``route_repositories`` → ``codegraph.services.repo_router_v2.RepoRouterV2.route``
- ``search_rag_chunks`` → ``services.retrieval.rag_search.search_rag``
- ``search_delivery_knowledge`` → ``knowledge.retrieval.DeliveryKnowledgeSearchService``
- ``search_learning_cases`` → ``mcp_tools.learning_case_service.search_learning_cases``
- ``summarize_branch`` → ``mcp_tools.merge_request_service.summarize_branch``
- ``create_learning_case`` → ``mcp_tools.learning_case_service.create_learning_case_from_technical_plan``
- ``report_project_knowledge`` → ``initiatives.services.MemoryService.create_draft``
  （``mcp_tools/views.py`` ``ReportProjectKnowledgeView`` draft 路径的底层 service）

返回值约定（统一做法，execute_builtin 会对非 ToolResult 返回 str()）：
**所有 handler 返回 ``json.dumps(..., ensure_ascii=False)`` 字符串**，保证步骤结果
在 skill results 列表中可读。缺必需参数 / 无法解析权限主体时返回含 ``error`` 键的
JSON 字符串而非抛裸异常（步骤失败语义由 ``execute_tool`` 的 ok=False 承载——仅
真异常路径）；其余异常正常上抛交由 executor 归一。

权限主体（fail-closed）：``search_delivery_knowledge`` / ``search_learning_cases`` /
``report_project_knowledge`` 的底层 service 以 user 为权限主体，handler 经可选
``user_id`` 入参解析（skill 顶层 arguments 透传即可注入每步）；解析不到返回
error JSON，绝不以特权身份兜底。

所有 handler 均 ``**kwargs`` 容忍多余键——skill 顶层输入合并透传进每步，
步骤只取自己认识的键。
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _json(payload: dict[str, Any]) -> str:
    """结果 JSON 化（default=str 兜底 UUID/datetime 等不可序列化对象）。"""
    return json.dumps(payload, ensure_ascii=False, default=str)


def _error(message: str, **extra: Any) -> str:
    return _json({"error": message, **extra})


async def _resolve_user(user_id: str | int | None) -> Any | None:
    """按 user_id 解析权限主体；缺失/不存在返回 None（调用方 fail-closed）。"""
    if user_id is None or str(user_id).strip() == "":
        return None
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.filter(id=user_id).afirst()


async def route_repositories(
    query: str = "",
    top_k: int = 3,
    repository_ids: list[str] | None = None,
    **kwargs: Any,
) -> str:
    """仓库路由（委托 ``RepoRouterV2.route``）。"""
    if not query.strip():
        return _error("缺少必需参数 query")
    from codegraph.services.repo_router_v2 import RepoRouterV2

    result = await RepoRouterV2.route(query, top_k=top_k, repository_ids=repository_ids or None)
    return _json(
        {
            "candidates": [c.to_dict() for c in result.candidates],
            "router_version": result.router_version,
            "auto_selected": result.auto_selected,
        }
    )


async def search_rag_chunks(
    query: str = "",
    repository_ids: list[str] | None = None,
    top_k: int = 10,
    branch_name: str | None = None,
    **kwargs: Any,
) -> str:
    """代码语义检索（委托 ``search_rag``，多仓参数按其现有 ``repo_ids`` 形态）。"""
    if not query.strip():
        return _error("缺少必需参数 query")
    if not repository_ids:
        return _error("缺少必需参数 repository_ids（可由 route_repositories 结果提供）")
    from services.retrieval.rag_search import search_rag

    snapshot = await search_rag(
        query, repo_ids=list(repository_ids), branch_name=branch_name, top_k=top_k
    )
    return _json(
        {
            "status": snapshot.status,
            "result_count": snapshot.result_count,
            "items": snapshot.items,
            "error": snapshot.error,
        }
    )


async def search_delivery_knowledge(
    query: str = "",
    top_k: int = 5,
    user_id: str | None = None,
    project_ids: list[str] | None = None,
    repository_ids: list[str] | None = None,
    entity_kinds: list[str] | None = None,
    **kwargs: Any,
) -> str:
    """交付知识检索（委托 ``DeliveryKnowledgeSearchService.search_similar``）。"""
    if not query.strip():
        return _error("缺少必需参数 query")
    user = await _resolve_user(user_id)
    if user is None:
        return _error("无法解析权限主体 user_id，拒绝检索（fail-closed）")
    from knowledge.exposure import serialize_search_results
    from knowledge.retrieval import DeliveryKnowledgeSearchService

    results = await DeliveryKnowledgeSearchService().search_similar(
        query,
        user=user,
        top_k=top_k,
        project_ids=project_ids or None,
        repository_ids=repository_ids or None,
        entity_kinds=entity_kinds or None,
    )
    serialized = serialize_search_results(results)
    return _json({"results": serialized, "total": len(serialized)})


async def search_learning_cases(
    query: str = "",
    work_item_type: str = "",
    repo_hints: list[str] | None = None,
    file_hints: list[str] | None = None,
    symbol_hints: list[str] | None = None,
    limit: int = 5,
    user_id: str | None = None,
    **kwargs: Any,
) -> str:
    """历史 learning case 检索（委托 ``learning_case_service.search_learning_cases``）。"""
    if not query.strip():
        return _error("缺少必需参数 query")
    user = await _resolve_user(user_id)
    if user is None:
        return _error("无法解析权限主体 user_id，拒绝检索（fail-closed）")
    from mcp_tools.learning_case_service import search_learning_cases as _search

    cases = await _search(
        query=query,
        work_item_type=work_item_type,
        repo_hints=list(repo_hints or []),
        file_hints=list(file_hints or []),
        symbol_hints=list(symbol_hints or []),
        limit=limit,
        user=user,
    )
    return _json({"cases": cases, "total": len(cases)})


async def summarize_branch(
    repository_id: str = "",
    source_branch: str = "",
    target_branch: str = "",
    max_files: int = 30,
    **kwargs: Any,
) -> str:
    """分支 diff 摘要（委托 ``merge_request_service.summarize_branch``）。"""
    if not repository_id.strip() or not source_branch.strip():
        return _error("缺少必需参数 repository_id / source_branch")
    from mcp_tools.merge_request_service import summarize_branch as _summarize
    from repositories.models import Repository

    repo = await Repository.objects.filter(id=repository_id).afirst()
    if repo is None:
        return _error(f"仓库不存在: {repository_id}")
    summary = await _summarize(
        repository=repo,
        source_branch=source_branch,
        target_branch=target_branch or repo.default_branch,
        max_files=max_files,
        trace=None,
    )
    return _json(summary)


async def create_learning_case(
    technical_plan_id: str = "",
    outcome: str = "",
    root_cause: str = "",
    solution_notes: str = "",
    tests: list[str] | None = None,
    **kwargs: Any,
) -> str:
    """learning case 沉淀（委托 ``create_learning_case_from_technical_plan``）。

    底层 service 要求 ``InteractionRun`` 审计锚点（run FK + 输出 run_id）；skill
    步骤链路无既有 run，此处新建一条 ``source="skill"`` 的 run 作审计锚（与
    /api/tools/execute/ 顶层 run 分离，不伪造 token 指纹）。
    """
    if not technical_plan_id.strip():
        return _error("缺少必需参数 technical_plan_id")
    from interactions.models import InteractionRun
    from mcp_tools.learning_case_service import create_learning_case_from_technical_plan

    run = await InteractionRun.objects.acreate(source="skill")
    result = await create_learning_case_from_technical_plan(
        run=run,
        technical_plan_id=technical_plan_id,
        outcome=outcome or "success",
        root_cause=root_cause,
        solution_notes=solution_notes,
        tests=list(tests or []),
    )
    return _json(result.output)


async def report_project_knowledge(
    project_id: str = "",
    content: str = "",
    user_id: str | None = None,
    source_conversation_id: str | None = None,
    **kwargs: Any,
) -> str:
    """项目知识上报（委托 ``MemoryService.create_draft`` —— draft 路径，绝不直写 active）。"""
    if not project_id.strip() or not content.strip():
        return _error("缺少必需参数 project_id / content")
    user = await _resolve_user(user_id)
    if user is None:
        return _error("无法解析权限主体 user_id，拒绝上报（fail-closed）")
    from initiatives.services import MemoryPermissionError, MemoryService

    try:
        draft = await MemoryService().create_draft(
            project_id=project_id,
            content=content,
            proposed_by=user,
            source_conversation_id=source_conversation_id,
            actor=user,
            initiated_by_user_id=str(user.id),
        )
    except MemoryPermissionError as exc:
        return _error(f"权限不足：{exc}")
    return _json({"accepted": True, "draft_id": str(draft.id)})
