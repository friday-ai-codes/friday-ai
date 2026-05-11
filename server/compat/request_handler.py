"""request_handler — OpenAI messages → LangChain BaseMessage + LayeredSearch 注入。"""
from __future__ import annotations
import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from codegraph.services.layered_search import LayeredSearchService
logger = structlog.get_logger(__name__)
async def prepare_messages(
 messages: list[dict],
 repository_ids: list[str] | None,
 project_id: str | None,
) -> list[BaseMessage]:
 """把 OpenAI messages 转换为 LangChain BaseMessage，并前置插入 RAG system message。：最后一条 user/developer message 作为 query 调 LayeredSearchService.search，
 final_context 非空时包装为 SystemMessage 前置；检索失败降级为 plain LLM 调用。
 三层 fallback：
 1. explicit repository_ids 非空 → 直接传入
 2. project_id 非空 → 由调用方解析后传入（本函数透传）
 3. 都没有 → 传 None，LayeredSearchService L1 RepoRouter 自动兜底
 """
 lc_messages: list[BaseMessage] =
 for m in messages:
 role = m.get("role", "")
 content = m.get("content", "")
 if role == "system":
 lc_messages.append(SystemMessage(content=content))
 elif role == "assistant":
 lc_messages.append(AIMessage(content=content))
 elif role in {"user", "developer"}:
 lc_messages.append(HumanMessage(content=content))
 # tool role 留待 处理
 # 把最后一条 user/developer message 作为 RAG query
 last_user = next(
 (m for m in reversed(messages) if m.get("role") in {"user", "developer"}),
 None,
 )
 if not last_user:
 return lc_messages
 try:
 # TODO(T-/): repository_ids 存在 IDOR 风险——未验证每个 UUID 是否属于调用方
 # 可访问范围（PermissionService.has_repository_access）。 暂不鉴权，启用
 # OPENAI_COMPAT_API_KEYS 后须在此加权限过滤，否则攻击者可读取任意仓库代码片段。
 result = await LayeredSearchService.search(
 query=str(last_user.get("content", "")),
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
 # 降级路径：检索失败不抛错，回退 plain LLM 调用
 logger.warning("compat_layered_search_failed", error=str(e))
 return lc_messages
