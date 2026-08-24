"""Chat Agent 的 canonical graph_query 薄适配面。"""

from __future__ import annotations

from copy import deepcopy

from agents.tools.base import ToolCategory, ToolResult, tool
from agents.tools.delivery_knowledge_tools import _resolve_conversation_user
from agents.tools.graph_tools import _record_chat_retrieval
from agents.tools.project_read_tools import _CONV_ID_PARAM
from common.logging import redact_secrets_in_text
from interactions.models import RetrievalTrace
from services.code_graph import GraphQueryService
from services.code_graph.query_manifest import graph_query_manifest

_manifest = graph_query_manifest()
_parameters = deepcopy(_manifest["inputSchema"])
_parameters["properties"].update(_CONV_ID_PARAM)
_parameters["required"] = [*_parameters["required"], "conversation_id"]


@tool(
    name=_manifest["name"],
    description=_manifest["description"],
    category=ToolCategory.PROJECT.value,
    parameters=_parameters,
)
async def graph_query(
    repository_id: str,
    query: str,
    branch: str = "",
    max_symbols: int = 10,
    max_processes: int = 5,
    budget_chars: int = 50_000,
    include_impact: bool = False,
    anchor_symbol_id: str | None = None,
    impact_max_depth: int = 3,
    impact_limit: int = 200,
    conversation_id: str = "",
) -> ToolResult:
    """只注入会话 owner/context，查询算法只存在于 GraphQueryService。"""
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(success=False, error="无法解析会话 owner，拒绝查询（fail-closed）")
    try:
        result = await GraphQueryService().query(
            query,
            repository_id=repository_id,
            branch_name=branch,
            user=user,
            initiated_by_user_id=str(user.id),
            max_symbols=max_symbols,
            max_processes=max_processes,
            budget_chars=budget_chars,
            include_impact=include_impact,
            anchor_symbol_id=anchor_symbol_id,
            impact_max_depth=impact_max_depth,
            impact_limit=impact_limit,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            success=False,
            error=redact_secrets_in_text(str(exc))[:500],
        )
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        {
            "source": "chat_graph_query",
            "scope": result["scope"],
            "partial": result["partial"],
            "symbol_count": result["symbols"]["returned_count"],
            "process_count": result["processes"]["returned_count"],
            "impact_status": result["impact"]["status"],
            "manifest_hash": result["manifest_hash"],
        },
        conversation_id=conversation_id,
        user=user,
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "contract_version": result["contract_version"],
                "manifest_hash": result["manifest_hash"],
                "conversation_id": conversation_id,
            },
        },
    )


__all__ = ["graph_query"]
