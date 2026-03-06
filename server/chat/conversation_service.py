"""ConversationService — 对话系统核心业务逻辑。
封装对话的 CRUD 操作和发送消息流程（AgentLoop 调用）。
所有方法为 async staticmethod，支持 Django async ORM。
"""
from __future__ import annotations
import uuid
from typing import Any
import structlog
from django.utils import timezone
from agents.core.context import AgentContext
from agents.core.loop import AgentConfig, AgentLoop
from agents.core.result import AgentResult
from agents.llm.base import create_provider
from chat.context_manager import DEFAULT_MAX_MESSAGES, truncate_messages
from chat.models import Conversation, Message
from chat.services import aget_setting_value
from system.models import SettingKeys
logger = structlog.get_logger(__name__)
def _build_system_prompt(project_name: str) -> str:
 """构建基础 system prompt。
 Phase 会替换为更完善的知识增强版本。
 """
 return (
 f"你是 Friday AI 项目助手，基于项目「{project_name}」的知识库回答问题。"
 f"请用中文回答，简洁准确。如果不确定，请说明。"
 )
def _extract_tool_calls(result: AgentResult) -> list[dict[str, Any]]:
 """从 AgentResult 中提取工具调用记录。
 工具调用详情在 AgentSession.ToolCallLog 中，
 Phase 可从那里获取完整信息。当前仅提取基本信息。
 """
 tool_calls: list[dict[str, Any]] =
 # 从 metadata 中提取（如果有）
 if result.metadata.get("tool_calls"):
 return result.metadata["tool_calls"]
 # 从 output 中提取 tool_use block
 for item in result.output:
 if isinstance(item, dict) and item.get("type") == "tool_use":
 tool_calls.append({
 "id": item.get("id", ""),
 "name": item.get("name", ""),
 "input": item.get("input", {}),
 })
 return tool_calls
class ConversationService:
 """对话系统业务逻辑服务。"""
 @staticmethod
 async def create_conversation(
 project_id: str,
 title: str = "新对话",
 ) -> Conversation:
 """创建新对话。
 Args:
 project_id: 项目 UUID
 title: 对话标题
 Returns:
 新创建的 Conversation 实例
 """
 conversation = await Conversation.objects.acreate(
 project_id=project_id,
 title=title,
 )
 logger.info(
 "conversation_created",
 conversation_id=str(conversation.id),
 project_id=project_id,
 title=title,
 )
 return conversation
 @staticmethod
 async def send_message(
 conversation_id: str,
 content: str,
 ) -> dict[str, Any]:
 """发送消息并获取 AI 回复。
 流程：保存 user 消息 -> 构建 messages -> 截断 -> AgentLoop.run
 -> 解析结果 -> 保存 assistant 消息 -> 更新 conversation.updated_at
 Args:
 conversation_id: 对话 UUID
 content: 用户消息内容
 Returns:
 包含 message、tool_calls、usage 的 dict
 """
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
 # 构建 messages 列表（仅 user/assistant，不加载 tool/system）
 db_messages = [
 msg async for msg in Message.objects.filter(
 conversation=conversation,
 role__in=[Message.Role.USER, Message.Role.ASSISTANT],
 ).order_by("created_at")
 ]
 messages = [
 {"role": msg.role, "content": msg.content}
 for msg in db_messages
 ]
 # 截断
 messages = truncate_messages(messages, max_messages=DEFAULT_MAX_MESSAGES)
 # 构建 AgentLoop
 session_id = f"chat-{conversation.id}-{uuid.uuid4.hex[:8]}"
 project_name = conversation.project.name
 # 获取 LLM 配置
 api_key = await aget_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 base_url = await aget_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or ""
 if not api_key:
 raise ValueError("未配置 Anthropic API Key，请在系统设置中配置")
 provider = create_provider(
 provider_type="anthropic",
 api_key=api_key,
 base_url=base_url,
 model=model,
 )
 config = AgentConfig(
 system_prompt=_build_system_prompt(project_name),
 max_iterations=15,
 max_tokens=4096,
 tool_names=, # 无工具，Phase 添加
 )
 context = AgentContext(
 session_id=session_id,
 project_id=1, # AgentContext 要求 int，此处为占位
 user_id=1,
 metadata={"conversation_id": str(conversation.id)},
 )
 loop = AgentLoop(config=config, context=context, provider=provider)
 # 执行
 result = await loop.run(content)
 # 解析结果
 tool_calls = _extract_tool_calls(result)
 final_content = result.final_answer or ""
 # 保存 assistant 消息
 assistant_msg = await Message.objects.acreate(
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content=final_content,
 tool_calls=tool_calls if tool_calls else None,
 metadata={
 "usage": result.usage,
 "iterations": result.metadata.get("iterations"),
 "status": result.status,
 },
 )
 # 更新对话时间
 await Conversation.objects.filter(id=conversation.id).aupdate(
 updated_at=timezone.now,
 )
 logger.info(
 "message_sent",
 conversation_id=str(conversation.id),
 status=result.status,
 usage=result.usage,
 )
 return {
 "message": assistant_msg,
 "tool_calls": tool_calls,
 "usage": result.usage,
 }
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
