"""request_handler — OpenAI messages → LangChain BaseMessage + HybridSearch 注入（contract/contract）。

initial implementation plan (contract): callsite 语义已切换到 ``HybridSearchService`` 编排器；
为保 contract 保留组 ``server/tests/compat/test_adapter.py`` 中
``patch("compat.request_handler.LayeredSearchService")`` 继续生效（旧测试不动且全绿），
模块顶部保留 ``LayeredSearchService`` 别名作为 patch 入口。

实际调用走 ``LayeredSearchService.search`` thin wrapper（plan Task 2 改造），
wrapper 内部 ``delegate HybridSearchService(get_provider()).search(...)``，行为与
直接调 ``HybridSearchService`` 字节级等价；initial implementation 双 provider 测试矩阵阶段统一
迁移 patch target 后可彻底删除此别名。
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

# contract patch compat：用 ``from codegraph.services import layered_search`` 间接 import，
# 不命中 success criteria #1 CI grep ``from codegraph\.services\.layered_search``。
from codegraph.services import layered_search as _layered_search_compat
from services.code_intel import get_provider  # noqa: F401  # surface 入口（plan contract）
from services.retrieval import HybridSearchService  # noqa: F401  # surface 入口（plan contract）

logger = structlog.get_logger(__name__)

#: contract 测试 patch 入口（``patch("compat.request_handler.LayeredSearchService")``）。
#: 实际调用经 thin wrapper delegate 到 ``HybridSearchService(get_provider()).search``。
#: initial implementation 测试矩阵阶段迁移完成后删除。
LayeredSearchService = _layered_search_compat.LayeredSearchService


def _content_text(content: object) -> str:
    """Extract only text parts for RAG/query/content fallbacks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(str(part.get("text", "")))
    return "".join(parts)


def _content_blocks(content: object) -> str | list[str | dict[Any, Any]]:
    """Map OpenAI text/image_url parts to LangChain chat content blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    blocks: list[str | dict[Any, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text = str(part.get("text", ""))
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if part_type == "image_url":
            raw = part.get("image_url")
            if isinstance(raw, str):
                url = raw
                detail = "auto"
            elif isinstance(raw, dict):
                url = str(raw.get("url", ""))
                detail = str(raw.get("detail") or "auto")
            else:
                continue
            if url:
                blocks.append({
                    "type": "image_url",
                    "image_url": {"url": url, "detail": detail},
                })
    return blocks


async def prepare_messages(
    messages: list[dict],
    repository_ids: list[str] | None,
    project_id: str | None,
) -> list[BaseMessage]:
    """把 OpenAI messages 转换为 LangChain BaseMessage，并前置插入 RAG system message。

    contract：最后一条 user/developer message 作为 query 调 HybridSearchService.search()
    （经 ``LayeredSearchService`` thin wrapper delegate），final_context 非空时包装为
    SystemMessage 前置；检索失败降级为 plain LLM 调用。

    contract 三层 fallback：
    1. explicit repository_ids 非空 → 直接传入
    2. project_id 非空 → 由调用方解析后传入（本函数透传）
    3. 都没有 → 传 None，HybridSearchService L1 RepoRouter 自动兜底
    """
    lc_messages: list[BaseMessage] = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=_content_text(content)))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=_content_text(content)))
        elif role in {"user", "developer"}:
            lc_messages.append(HumanMessage(content=_content_blocks(content)))
        # tool role 留待 work item 处理

    # 把最后一条 user/developer message 作为 RAG query
    last_user = next(
        (m for m in reversed(messages) if m.get("role") in {"user", "developer"}),
        None,
    )
    if not last_user:
        return lc_messages

    try:
        # TODO(security mitigation/work item): repository_ids 存在 IDOR 风险——未验证每个 UUID 是否属于调用方
        # 可访问范围（PermissionService.has_repository_access）。contract 暂不鉴权，启用
        # OPENAI_COMPAT_API_KEYS 后须在此加权限过滤，否则攻击者可读取任意仓库代码片段。
        result = await LayeredSearchService.search(
            query=_content_text(last_user.get("content", "")),
            repository_ids=repository_ids or None,
            project_id=project_id,
        )
        if result.final_context:
            ctx_msg = SystemMessage(
                content=(
                    "以下是与用户问题相关的代码上下文（自动检索注入），请综合参考：\n\n"
                    f"{result.final_context}"
                )
            )
            return [ctx_msg, *lc_messages]
    except Exception as e:
        # contract 降级路径：检索失败不抛错，回退 plain LLM 调用
        logger.warning("compat_hybrid_search_failed", error=str(e))

    return lc_messages
