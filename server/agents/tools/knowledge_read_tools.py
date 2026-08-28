"""Chat 知识读工具集（Phase 102 KNOW-05）。

给 Chat 对话补三个白名单知识读工具，让 LLM 能主动读统一知识库：

- ``search_learning_cases``   —— 历史任务经验检索（LearningCase 向量版，挂 _INDEXED）
- ``search_project_context``  —— 项目沉淀语义检索（挂 _PROJECT_READ，需 bound_project）
- ``read_project_doc``        —— 项目工作区单文档读取（挂 _PROJECT_READ）

**薄封装铁律**：不写新业务逻辑，只做权限前置 + service 转调 + 结果映射 + 埋点。

- 权限 fail-closed：``search_learning_cases`` 凭会话 owner（``_resolve_conversation_user``
  先例，delivery_knowledge_tools）；另两个凭 ``bound_project`` 成员 / ``public_org``
  （``_resolve_project_scope`` 先例，project_read_tools）；解析失败零结果零泄漏。
- Chat 链召回写 ``RetrievalTrace``（``conversation_id`` 关联、``source="chat"``、
  best-effort 吞异常绝不反噬对话主流程）；payload 只记计数 / score / 耗时 / 维度键，
  绝不记召回正文（T-102-07）。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog

from agents.tools.base import ToolCategory, ToolResult, tool
from agents.tools.delivery_knowledge_tools import _resolve_conversation_user
from agents.tools.project_read_tools import _CONV_ID_PARAM, _deny, _resolve_project_scope
from common.logging import redact_secrets_in_text
from knowledge.exposure import serialize_search_results
from knowledge.retrieval import DeliveryKnowledgeSearchService

logger = structlog.get_logger(__name__)

_COMPONENT = "agents.tools"

# service 单例（对齐 delivery_knowledge_tools 模块级单例范式）。
_service = DeliveryKnowledgeSearchService()


async def _record_chat_retrieval(
    kind: str,
    payload: dict[str, Any],
    *,
    conversation_id: str,
    user: Any,
) -> None:
    """Chat 链召回留痕（RetrievalTrace，conversation_id 关联；best-effort 吞异常）。"""
    try:
        from interactions.ledger import arecord_retrieval_trace

        await arecord_retrieval_trace(
            None,
            kind=kind,
            payload=payload,
            user_id=str(user.id) if user else None,
            conversation_id=conversation_id,
            source="chat",
        )
    except Exception:  # noqa: BLE001 — 留痕 best-effort，绝不反噬对话主流程
        pass


_DESC_LEARNING_CASES = (
    "检索历史任务经验（LearningCase：根因 / 解法 / 已验证测试）。统一向量检索，"
    "repo_hints / file_hints / symbol_hints 作为查询增强与排序提权（不是硬过滤）。\n"
    "USE WHEN：开始新需求 / 修 bug 前找「以前有没有做过类似任务、踩过什么坑」的案例级经验。\n"
    "与 search_delivery_knowledge 的分工：本工具查**案例级经验**（单任务的根因/解法沉淀），"
    "search_delivery_knowledge 查**交付实体图谱**（需求→方案→代码变更链路）。"
)

_DESC_PROJECT_CONTEXT = (
    "语义检索「当前项目」的全部沉淀（工作区 5 文件 / 记忆 / 工件 / 需求 / 方案）。"
    "回答「项目里关于 X 的上下文 / 项目有没有沉淀过 X」时用。仅项目对话有效"
    "（对话需绑定项目）。"
)

_DESC_SESSION_KNOWLEDGE = (
    "按必填 repository_id 检索已入图的中高价值 session_capture 会话精华；"
    "可选 project_id 只与仓库范围做 AND 收窄。"
)

_DESC_READ_PROJECT_DOC = (
    "读「当前项目」工作区单文档的渲染 markdown 与 block 分区。"
    "看项目记忆 / 状态 / 里程碑原文时用。仅项目对话有效（对话需绑定项目）。"
)


@tool(
    name="search_session_knowledge",
    description=_DESC_SESSION_KNOWLEDGE,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "会话知识检索 query"},
            "repository_id": {"type": "string", "description": "必填仓库 UUID，主检索范围"},
            "project_id": {
                "type": "string",
                "description": "可选项目 UUID，仅用于 AND 收窄",
            },
            "top_k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
            **_CONV_ID_PARAM,
        },
        "required": ["query", "repository_id", "conversation_id"],
    },
)
async def search_session_knowledge(
    query: str,
    repository_id: str,
    project_id: str | None = None,
    top_k: int = 5,
    conversation_id: str = "",
) -> ToolResult:
    started = perf_counter()
    top_k = max(1, min(int(top_k), 20))
    logger.info(
        "search_session_knowledge_started",
        repository_id=repository_id,
        component=_COMPONENT,
        category="caller",
    )
    user = await _resolve_conversation_user(conversation_id)
    if user is None or not repository_id.strip():
        logger.warning(
            "search_session_knowledge_failed",
            repository_id=repository_id,
            reason="conversation_owner_or_repository_missing",
            duration_ms=int((perf_counter() - started) * 1000),
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error="无法解析会话 owner 或仓库，拒绝检索（fail-closed）")

    from knowledge.session_capture_retrieval import (
        search_session_knowledge as _search_session_knowledge,
    )

    try:
        results = await _search_session_knowledge(
            query=query,
            user=user,
            repository_id=repository_id,
            project_id=project_id or None,
            top_k=top_k,
        )
    except Exception as exc:  # noqa: BLE001 — 检索失败转工具错误，不抛
        safe_err = redact_secrets_in_text(str(exc))
        logger.exception(
            "search_session_knowledge_failed",
            repository_id=repository_id,
            error=safe_err,
            duration_ms=int((perf_counter() - started) * 1000),
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=f"检索失败: {safe_err}")

    serialized = serialize_search_results(results)
    duration_ms = int((perf_counter() - started) * 1000)
    scores = [float(item.get("score") or 0) for item in serialized]
    await _record_chat_retrieval(
        "chunk",
        {
            "source": "chat_search_session_knowledge",
            "repository_id": repository_id,
            "project_id": project_id or "",
            "source_kind": "session_capture",
            "result_count": len(serialized),
            "scores": scores,
            "top_score": max(scores) if scores else 0,
            "duration_ms": duration_ms,
        },
        conversation_id=conversation_id,
        user=user,
    )
    logger.info(
        "search_session_knowledge_completed",
        repository_id=repository_id,
        result_count=len(serialized),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
    )
    return ToolResult(
        success=True,
        output={"query": query, "results": serialized, "total": len(serialized)},
    )


@tool(
    name="search_learning_cases",
    description=_DESC_LEARNING_CASES,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "自然语言检索 query"},
            "work_item_type": {
                "type": "string",
                "description": "工作项类型过滤（如 story / bug，可选）",
                "default": "",
            },
            "repo_hints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "相关仓库名提示（查询增强 + 排序提权）",
            },
            "file_hints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "相关文件路径提示（查询增强 + 排序提权）",
            },
            "symbol_hints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "相关符号名提示（查询增强 + 排序提权）",
            },
            "limit": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
            **_CONV_ID_PARAM,
        },
        "required": ["query"],
    },
)
async def search_learning_cases(
    query: str,
    work_item_type: str = "",
    repo_hints: list[str] | None = None,
    file_hints: list[str] | None = None,
    symbol_hints: list[str] | None = None,
    limit: int = 5,
    conversation_id: str = "",
) -> ToolResult:
    started = perf_counter()
    # 102-REVIEW LO-02：LLM 直出参数钳上下界（对齐 MCP serializer max_value=20），
    # 防 limit=10000 之类放大为 top_k=30000 打 Qdrant。
    limit = max(1, min(int(limit), 20))
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(success=False, error="无法解析会话 owner，拒绝检索（fail-closed）")
    # 函数内延迟 import：避免模块级跨 app import 环（agents ↔ mcp_tools）。
    from mcp_tools.learning_case_service import search_learning_cases as _search_cases

    try:
        results = await _search_cases(
            query=query,
            work_item_type=work_item_type or "",
            repo_hints=repo_hints or [],
            file_hints=file_hints or [],
            symbol_hints=symbol_hints or [],
            limit=limit,
            user=user,
        )
    except Exception as exc:  # noqa: BLE001 — 检索失败转工具错误，不抛
        # 102-REVIEW LO-01：异常文本先脱敏再写日志 / 返回 LLM（进入对话消息与留痕）
        safe_err = redact_secrets_in_text(str(exc))
        logger.exception("search_learning_cases_failed", error=safe_err)
        return ToolResult(success=False, error=f"检索失败: {safe_err}")
    duration_ms = round((perf_counter() - started) * 1000, 2)
    scores = [float(item.get("score") or 0) for item in results]
    await _record_chat_retrieval(
        "chunk",
        {
            "source": "chat_search_learning_cases",
            "result_count": len(results),
            "scores": scores,
            "top_score": max(scores) if scores else 0,
            "duration_ms": duration_ms,
            "work_item_type": work_item_type or "",
            "limit": limit,
        },
        conversation_id=conversation_id,
        user=user,
    )
    logger.info(
        "search_learning_cases_done",
        conversation_id=conversation_id,
        result_count=len(results),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
    )
    return ToolResult(
        success=True,
        output={"query": query, "results": results, "total": len(results)},
    )


@tool(
    name="search_project_context",
    description=_DESC_PROJECT_CONTEXT,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "自然语言检索 query"},
            "top_k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
            "entity_kinds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "实体类型过滤（可选，如 document / work_item / tech_plan）",
            },
            **_CONV_ID_PARAM,
        },
        "required": ["query", "conversation_id"],
    },
)
async def search_project_context(
    query: str,
    top_k: int = 5,
    entity_kinds: list[str] | None = None,
    conversation_id: str = "",
) -> ToolResult:
    started = perf_counter()
    # 102-REVIEW LO-02：LLM 直出参数钳上下界（对齐 MCP serializer max_value=20）。
    top_k = max(1, min(int(top_k), 20))
    project, user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)
    try:
        # 参数口径对齐 MCP SearchProjectContextView：项目 id 收口 + document kind 纳入召回。
        results = await _service.search_similar(
            query,
            user=user,
            project_ids=[str(project.id)],
            entity_kinds=entity_kinds or None,
            top_k=top_k,
            include_document_kind=True,
        )
    except Exception as exc:  # noqa: BLE001 — 检索失败转工具错误，不抛
        # 102-REVIEW LO-01：异常文本先脱敏再写日志 / 返回 LLM（进入对话消息与留痕）
        safe_err = redact_secrets_in_text(str(exc))
        logger.exception("search_project_context_failed", error=safe_err)
        return ToolResult(success=False, error=f"检索失败: {safe_err}")
    serialized = serialize_search_results(results)
    duration_ms = round((perf_counter() - started) * 1000, 2)
    scores = [item.get("score", 0) for item in serialized]
    await _record_chat_retrieval(
        "chunk",
        {
            "source": "chat_search_project_context",
            "project_id": str(project.id),
            "result_count": len(serialized),
            "scores": scores,
            "top_score": max(scores) if scores else 0,
            "duration_ms": duration_ms,
        },
        conversation_id=conversation_id,
        user=user,
    )
    logger.info(
        "search_project_context_done",
        conversation_id=conversation_id,
        project_id=str(project.id),
        result_count=len(serialized),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
    )
    return ToolResult(
        success=True,
        output={
            "project_id": str(project.id),
            "query": query,
            "results": serialized,
            "total": len(serialized),
        },
    )


@tool(
    name="read_project_doc",
    description=_DESC_READ_PROJECT_DOC,
    category=ToolCategory.KNOWLEDGE.value,
    parameters={
        "type": "object",
        "properties": {
            "doc_type": {
                "type": "string",
                "description": "文档类型，合法值：memory / state / milestones / research / preflight",
            },
            **_CONV_ID_PARAM,
        },
        "required": ["doc_type", "conversation_id"],
    },
)
async def read_project_doc(
    doc_type: str = "",
    conversation_id: str = "",
) -> ToolResult:
    started = perf_counter()
    project, user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)
    # 函数内延迟 import：avoid agents ↔ initiatives 模块级 import 环。
    from initiatives.services.doc_content_service import DocContentService

    try:
        rendered = await DocContentService().get_doc_render(
            project_id=str(project.id), doc_type=doc_type
        )
    except Exception as exc:  # noqa: BLE001 — 读取失败转工具错误，不抛
        # 102-REVIEW LO-01：异常文本先脱敏再写日志 / 返回 LLM（进入对话消息与留痕）
        safe_err = redact_secrets_in_text(str(exc))
        logger.exception("read_project_doc_failed", error=safe_err)
        return ToolResult(success=False, error=f"读取失败: {safe_err}")
    if rendered is None:
        return ToolResult(success=False, error="工作区文件不存在")
    blocks = rendered.get("blocks", []) or []
    duration_ms = round((perf_counter() - started) * 1000, 2)
    await _record_chat_retrieval(
        "file",
        {
            "source": "chat_read_project_doc",
            "project_id": str(project.id),
            "doc_type": doc_type,
            "block_count": len(blocks),
            "duration_ms": duration_ms,
        },
        conversation_id=conversation_id,
        user=user,
    )
    logger.info(
        "read_project_doc_done",
        conversation_id=conversation_id,
        project_id=str(project.id),
        doc_type=doc_type,
        block_count=len(blocks),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
    )
    return ToolResult(
        success=True,
        output={
            "project_id": str(project.id),
            "doc_type": doc_type,
            "rendered_markdown": rendered.get("rendered_markdown", "") or "",
            "blocks": blocks,
        },
    )


__all__ = [
    "search_learning_cases",
    "search_session_knowledge",
    "search_project_context",
    "read_project_doc",
]
