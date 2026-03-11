"""ConversationService — 对话系统核心业务逻辑。
封装对话的 CRUD 操作和发送消息流程（SDKAgentRunner 调用）。
所有方法为 async staticmethod，支持 Django async ORM。
"""
from __future__ import annotations
import uuid
from collections.abc import AsyncGenerator
from typing import Any
import structlog
from django.utils import timezone
from agents.core.events import (
 AgentEvent,
 ERROR,
 MESSAGE_COMPLETE,
 TITLE_GENERATED,
)
from agents.models import AgentSession, ToolCallLog
from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
from chat.models import Conversation, Message
from chat.services import aget_setting_value
from repositories.models import Repository
from services.provider_config import ProviderConfigError, ProviderConfigService
from system.models import SettingKeys
# 触发 @tool 注册，确保 chat_tools 中定义的工具在 ToolRegistry 中可用
import agents.tools.chat_tools # noqa: F401
logger = structlog.get_logger(__name__)
# ============================================================================
# 角色化 System Prompt
# ============================================================================
ROLE_PROMPTS: dict[str, str] = {
 "developer": (
 "你是一名资深开发工程师助手。回答问题时关注代码细节、技术实现方案和最佳实践。"
 "使用专业技术术语，提供代码示例和具体的文件路径引用。"
 "分析问题时从架构设计、性能影响和可维护性角度出发。"
 ),
 "pm": (
 "你是一名项目经理助手。回答问题时关注项目进度、风险评估和资源依赖关系。"
 "使用业务术语，避免过多技术细节。"
 "以要点和时间线形式组织回答，突出影响和优先级。"
 ),
 "designer": (
 "你是一名设计师助手。回答问题时关注用户交互流程、视觉一致性和用户体验。"
 "关注界面布局、信息层级和操作流畅度。"
 "从用户视角分析问题，提供交互优化建议。"
 ),
 "qa": (
 "你是一名 QA 工程师助手。回答问题时关注测试覆盖、边界条件和潜在缺陷模式。"
 "分析代码时识别可能的异常路径、数据验证漏洞和并发问题。"
 "提供具体的测试用例建议和回归测试策略。"
 ),
 "general": (
 "你是一名全能项目助手。根据问题性质平衡技术细节和业务概览。"
 "灵活调整回答深度，简单问题简洁回答，复杂问题详细分析。"
 ),
}
VALID_ROLES = frozenset(ROLE_PROMPTS.keys)
def _build_system_prompt(
 project_name: str,
 project_id: str,
 role: str = "developer",
) -> str:
 """构建角色化 system prompt。
 根据用户选择的角色生成差异化的 system prompt，
 影响 AI 的回答风格、关注点和术语级别。
 Args:
 project_name: 项目名称
 project_id: 项目 UUID（供工具调用时使用）
 role: 用户角色（developer/pm/designer/qa/general），无效值回退 general
 Returns:
 完整的 system prompt 字符串
 """
 role_prompt = ROLE_PROMPTS.get(role, ROLE_PROMPTS["general"])
 return (
 f"{role_prompt}\n\n"
 f"你正在为项目「{project_name}」（project_id: {project_id}）提供帮助。"
 f"调用工具时请使用此 project_id。"
 f"基于项目知识库回答，如果不确定请说明。用中文回答。"
 )
async def _get_tool_names(project_id: str) -> list[str]:
 """根据项目仓库索引状态返回可用工具列表。
 有已索引仓库：注入全部 6 个工具（3 个新检索工具 + 3 个已有项目工具）
 无仓库或未索引：仅注入 get_project_overview（基础信息）
 """
 base_tools = ["get_project_overview"]
 full_tools = base_tools + [
 "browse_file_content",
 "list_project_structure",
 "search_repository_code",
 "list_project_repositories",
 "get_repository_info",
 ]
 has_indexed = await Repository.objects.filter(
 projects__id=project_id,
 index_status="indexed",
 is_deleted=False,
 ).aexists
 return full_tools if has_indexed else base_tools
def _coerce_reference_item(
 tool_name: str,
 result_output: dict[str, Any],
 fallback_repo: str,
) -> dict[str, Any] | None:
 path = str(
 result_output.get("path")
 or result_output.get("file_path")
 or result_output.get("file")
 or ""
 )
 line_start = result_output.get("line_start") or result_output.get("start_line")
 line_end = result_output.get("line_end") or result_output.get("end_line")
 summary = str(
 result_output.get("summary")
 or result_output.get("snippet")
 or result_output.get("content_preview")
 or result_output.get("text")
 or ""
 ).strip
 if not (path or summary):
 return None
 line = ""
 if line_start and line_end:
 line = f"L{line_start}-L{line_end}"
 elif line_start:
 line = f"L{line_start}"
 return {
 "repository": fallback_repo,
 "path": path,
 "line": line,
 "tool_name": tool_name,
 "summary": summary[:160],
 }
def _extract_reference_candidates(tool_name: str, arguments: dict[str, Any], result_output: Any) -> list[dict[str, Any]]:
 repo = str(
 arguments.get("repository")
 or arguments.get("repository_name")
 or arguments.get("repo")
 or "项目上下文"
 )
 items: list[dict[str, Any]] =
 if isinstance(result_output, dict):
 candidate = _coerce_reference_item(tool_name, result_output, repo)
 if candidate:
 items.append(candidate)
 for key in ("results", "items", "matches"):
 values = result_output.get(key)
 if not isinstance(values, list):
 continue
 for value in values[:5]:
 if isinstance(value, dict):
 candidate = _coerce_reference_item(tool_name, value, repo)
 if candidate:
 items.append(candidate)
 elif isinstance(result_output, list):
 for value in result_output[:5]:
 if isinstance(value, dict):
 candidate = _coerce_reference_item(tool_name, value, repo)
 if candidate:
 items.append(candidate)
 return items
async def extract_reference_summaries(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
 """Summarize tool-call outputs for compact card-friendly references."""
 if not session_id:
 return
 references: list[dict[str, Any]] =
 seen: set[tuple[str, str, str]] = set
 logs = ToolCallLog.objects.filter(
 session__session_id=session_id,
 result_success=True,
 ).order_by("started_at")
 async for log in logs:
 for item in _extract_reference_candidates(log.tool_name, log.arguments or {}, log.result_output):
 key = (item["repository"], item["path"], item["line"])
 if key in seen:
 continue
 seen.add(key)
 references.append(item)
 if len(references) >= limit:
 return references
 return references
class ConversationService:
 """对话系统业务逻辑服务。"""
 @staticmethod
 async def create_conversation(
 project_id: str,
 title: str = "新对话",
 model: str = "",
 ) -> Conversation:
 """创建新对话。
 Args:
 project_id: 项目 UUID
 title: 对话标题
 model: LLM 模型 ID（为空时运行时使用系统默认）
 Returns:
 新创建的 Conversation 实例
 """
 conversation = await Conversation.objects.acreate(
 project_id=project_id,
 title=title,
 model=model,
 )
 logger.info(
 "conversation_created",
 conversation_id=str(conversation.id),
 project_id=project_id,
 title=title,
 )
 return conversation
 @staticmethod
 async def send_message_stream(
 conversation_id: str,
 content: str,
 role: str = "developer",
 ) -> AsyncGenerator[AgentEvent, None]:
 """流式发送消息，通过 SDKAgentRunner 驱动对话。
 SDKAgentRunner 在独立 asyncio.Task 中运行 SDK，通过 Queue 与
 generator 通信。SSE 断线后 Task 继续运行至完成，确保消息落库。
 Args:
 conversation_id: 对话 UUID
 content: 用户消息内容
 role: 用户角色
 Yields:
 AgentEvent 实例
 """
 from chat.title_service import generate_title, should_generate_title
 # 获取对话
 conversation = await Conversation.objects.select_related("project").aget(
 id=conversation_id,
 is_deleted=False,
 )
 # 保存 user 消息
 await Message.objects.acreate(
 conversation=conversation,
 role=Message.Role.USER,
 content=content,
 )
 # 预生成 assistant 消息 ID
 assistant_msg_id = uuid.uuid4
 # 解析 API key
 try:
 resolved = await ProviderConfigService.aresolve(
 conversation=conversation,
 project=conversation.project,
 )
 except ProviderConfigError as e:
 raise ValueError(str(e)) from e
 api_key = resolved.api_key
 # model 解析：对话级 > 系统级
 system_model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or ""
 model = conversation.model or system_model
 # 构建配置
 session_id = f"chat-{conversation.id}-{uuid.uuid4.hex[:8]}"
 project_name = conversation.project.name
 project_id = str(conversation.project_id)
 # 创建 AgentSession（用于 Hook 持久化）
 agent_session = await AgentSession.objects.acreate(
 session_id=session_id,
 project=conversation.project,
 user_id=1, # 占位，chat 路径暂无真实 user
 status=AgentSession.Status.RUNNING,
 metadata={"conversation_id": str(conversation.id)},
 )
 config = SdkRunnerConfig(
 system_prompt=_build_system_prompt(project_name, role=role),
 model=model,
 project_id=project_id,
 session_id=session_id,
 api_key=api_key,
 max_turns=15,
 agent_session=agent_session,
 )
 runner = SDKAgentRunner(config)
 # 流式 yield 事件，拦截 message_complete 补充字段
 try:
 async for event in runner.stream(content):
 if event.type == MESSAGE_COMPLETE:
 # 补充前端契约要求的字段
 result = runner.result
 event.data.setdefault("usage", result.usage if result else {})
 event.data.setdefault("status", result.status if result else "completed")
 event.data.setdefault("iterations", 0)
 event.data.setdefault("model", model)
 yield event
 except GeneratorExit:
 logger.info(
 "sse_disconnected",
 conversation_id=str(conversation_id),
 )
 return
 # 流结束后：落库
 result = runner.result
 final_content = result.final_answer if result else ""
 # 保存 assistant 消息
 await Message.objects.acreate(
 id=assistant_msg_id,
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content=final_content,
 metadata={
 "session_id": session_id,
 "model": model,
 "status": result.status if result else "unknown",
 },
 )
 # 更新对话时间
 await Conversation.objects.filter(id=conversation.id).aupdate(
 updated_at=timezone.now,
 )
 # 检查是否需要生成标题
 if await should_generate_title(str(conversation.id)):
 title = await generate_title(str(conversation.id), content)
 if title:
 yield AgentEvent(
 type=TITLE_GENERATED,
 data={"title": title},
 )
 logger.info(
 "stream_message_sent",
 conversation_id=str(conversation.id),
 session_id=session_id,
 status=result.status if result else "unknown",
 )
 @staticmethod
 async def list_conversations -> list[Conversation]:
 """返回未删除对话列表，按 updated_at 降序。"""
 return [
 c async for c in Conversation.objects.filter(
 is_deleted=False,
 ).order_by("-updated_at")
 ]
 @staticmethod
 async def get_conversation_with_messages(
 conversation_id: str,
 ) -> dict[str, Any]:
 """返回对话详情 + 全部历史消息。
 Args:
 conversation_id: 对话 UUID
 Returns:
 包含 conversation 和 messages 的 dict
 Raises:
 Conversation.DoesNotExist: 对话不存在或已删除
 """
 conversation = await Conversation.objects.aget(
 id=conversation_id,
 is_deleted=False,
 )
 messages = [
 msg async for msg in Message.objects.filter(
 conversation=conversation,
 ).order_by("created_at")
 ]
 return {
 "conversation": conversation,
 "messages": messages,
 }
 @staticmethod
 async def delete_conversation(conversation_id: str) -> None:
 """软删除对话。
 Args:
 conversation_id: 对话 UUID
 Raises:
 Conversation.DoesNotExist: 对话不存在或已删除
 """
 updated = await Conversation.objects.filter(
 id=conversation_id,
 is_deleted=False,
 ).aupdate(is_deleted=True)
 if updated == 0:
 raise Conversation.DoesNotExist(
 f"对话不存在或已删除: {conversation_id}"
 )
 logger.info(
 "conversation_deleted",
 conversation_id=conversation_id,
 )
