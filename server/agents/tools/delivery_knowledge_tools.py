"""交付知识 chat agent tools（Phase 16-02 EXPO-03）。"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from pydantic import ValidationError

from agents.tools.base import ToolCategory, ToolResult, tool
from chat.models import Conversation
from knowledge.exposure import (
    parse_as_of,
    serialize_related,
    serialize_search_results,
    serialize_timeline,
)
from knowledge.retrieval import DeliveryKnowledgeSearchService

logger = structlog.get_logger(__name__)

_service = DeliveryKnowledgeSearchService()

_TOOL_DESCRIPTION_SEARCH = (
    "检索历史交付知识（需求、技术方案、代码变更），回答「以前做过类似需求吗」。\n"
    "\n"
    "USE WHEN：自然语言相似需求 / 历史方案 / 交付链路追溯。\n"
    "DO NOT USE：纯代码仓库 RAG → search_repository_code；"
    "代码图遍历 → find_related_code。\n"
    "\n"
    "决策树：\n"
    '  - "以前做过登录优化吗" → search_delivery_knowledge(query=...)\n'
    '  - "谁调用了 foo()" → find_related_code\n'
    '  - "password validation 代码在哪" → search_repository_code'
)

_TOOL_DESCRIPTION_TIMELINE = (
    "获取交付实体的版本迭代时间线（需求→方案→代码变更）。\n"
    "USE WHEN：已知 entity_id，需要看版本历史。\n"
    "可选 as_of 查询历史时点。"
)

_TOOL_DESCRIPTION_RELATED = (
    "从实体出发多跳扩散关联实体（HAS_PLAN / IMPLEMENTED_BY 等）。\n"
    "USE WHEN：需要追溯需求→方案→代码变更链。\n"
    "可选 as_of 查询历史时点。"
)


async def _resolve_conversation_user(conversation_id: str):
    if not conversation_id:
        return None
    try:
        conversation = await Conversation.objects.select_related("created_by").aget(
            id=conversation_id
        )
    except (Conversation.DoesNotExist, ValueError):
        return None
    return conversation.created_by


@tool(
    name="search_delivery_knowledge",
    description=_TOOL_DESCRIPTION_SEARCH,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "自然语言检索 query"},
            "top_k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
            "project_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "限定项目 scope",
            },
            "repository_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "限定仓库 scope",
            },
            "entity_kinds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "实体类型过滤",
            },
            "as_of": {"type": "string", "description": "历史时点 ISO8601（可选）"},
            "include_superseded": {
                "type": "boolean",
                "description": "是否包含已取代版本",
                "default": False,
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 ID（由 chat_runner 注入）",
            },
        },
        "required": ["query"],
    },
)
async def search_delivery_knowledge(
    query: str,
    top_k: int = 5,
    project_ids: list[str] | None = None,
    repository_ids: list[str] | None = None,
    entity_kinds: list[str] | None = None,
    as_of: str | None = None,
    include_superseded: bool = False,
    conversation_id: str = "",
) -> ToolResult:
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(success=False, error="无法解析会话 owner，拒绝检索（fail-closed）")
    try:
        as_of_dt = parse_as_of(as_of)
    except ValueError:
        return ToolResult(success=False, error="as_of 格式无效，请使用带时区的 ISO8601")
    try:
        results = await _service.search_similar(
            query,
            user=user,
            top_k=top_k,
            project_ids=project_ids or None,
            repository_ids=repository_ids or None,
            entity_kinds=entity_kinds or None,
            as_of=as_of_dt,
            include_superseded=include_superseded,
        )
    except Exception as exc:
        logger.exception("delivery_knowledge_search_failed", error=str(exc))
        return ToolResult(success=False, error=f"检索失败: {exc}")
    serialized = serialize_search_results(results)
    return ToolResult(
        success=True,
        output={
            "query": query,
            "results": serialized,
            "total": len(serialized),
            "as_of": as_of_dt.isoformat() if as_of_dt else None,
        },
    )


@tool(
    name="get_entity_timeline",
    description=_TOOL_DESCRIPTION_TIMELINE,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "实体 UUID"},
            "include_superseded": {"type": "boolean", "default": False},
            "as_of": {"type": "string", "description": "历史时点 ISO8601（可选）"},
            "conversation_id": {"type": "string", "description": "会话 ID（注入）"},
        },
        "required": ["entity_id"],
    },
)
async def get_entity_timeline(
    entity_id: str,
    include_superseded: bool = False,
    as_of: str | None = None,
    conversation_id: str = "",
) -> ToolResult:
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(success=False, error="无法解析会话 owner，拒绝检索（fail-closed）")
    try:
        as_of_dt = parse_as_of(as_of)
        eid = uuid.UUID(str(entity_id))
    except ValueError as exc:
        return ToolResult(success=False, error=f"参数无效: {exc}")
    nodes = await _service.get_timeline(
        eid, user=user, include_superseded=include_superseded, as_of=as_of_dt
    )
    serialized = serialize_timeline(nodes)
    return ToolResult(
        success=True,
        output={"entity_id": str(eid), "nodes": serialized, "total": len(serialized)},
    )


@tool(
    name="get_related_entities",
    description=_TOOL_DESCRIPTION_RELATED,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "实体 UUID"},
            "direction": {
                "type": "string",
                "enum": ["both", "out", "in"],
                "default": "both",
            },
            "max_hops": {"type": "integer", "default": 2},
            "as_of": {"type": "string", "description": "历史时点 ISO8601（可选）"},
            "conversation_id": {"type": "string", "description": "会话 ID（注入）"},
        },
        "required": ["entity_id"],
    },
)
async def get_related_entities(
    entity_id: str,
    direction: str = "both",
    max_hops: int = 2,
    as_of: str | None = None,
    conversation_id: str = "",
) -> ToolResult:
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(success=False, error="无法解析会话 owner，拒绝检索（fail-closed）")
    try:
        as_of_dt = parse_as_of(as_of)
        eid = uuid.UUID(str(entity_id))
    except ValueError as exc:
        return ToolResult(success=False, error=f"参数无效: {exc}")
    related = await _service.get_related(
        eid, user=user, direction=direction, max_hops=max_hops, as_of=as_of_dt
    )
    serialized = serialize_related(related)
    return ToolResult(
        success=True,
        output={
            "entity_id": str(eid),
            "related": serialized,
            "total": len(serialized),
            "as_of": as_of_dt.isoformat() if as_of_dt else None,
        },
    )
