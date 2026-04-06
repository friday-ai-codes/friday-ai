"""会话收尾逻辑 — graph 完成后的消息落库、标题生成和通知。"""
from __future__ import annotations
import uuid
from typing import Any
import structlog
from django.utils import timezone
from agents.core.events import TITLE_GENERATED, AgentEvent
from agents.models import AgentSession
from chat.models import Conversation, Message
logger = structlog.get_logger(__name__)
async def finalize_conversation(
 *,
 conversation: Conversation,
 assistant_msg_id: uuid.UUID,
 final_content: str,
 accumulated_thinking: list[str],
 tool_calls: list[dict[str, Any]],
 result_metadata: dict[str, Any],
 agent_session: AgentSession,
 session_id: str,
 model: str,
 user_message: str,
 notification_user_id: str | None = None,
 publish_title_event: bool = True,
) -> list[AgentEvent]:
 """会话收尾：消息落库、AgentSession 更新、标题生成和 push 通知。
 从 graph terminal state 的数据构建 assistant 消息并持久化。
 提取自 ConversationService.send_message_stream 中的 finalize_conversation
 内部函数，改为从参数而非闭包变量获取数据。
 Returns:
 附加事件列表（标题生成等）
 """
 from chat.title_service import generate_title, should_generate_title
 final_events: list[AgentEvent] =
 # 1. 更新 AgentSession 最终状态
 try:
 status_str = result_metadata.get("status", "unknown")
 if status_str == "completed":
 session_status = AgentSession.Status.COMPLETED
 elif status_str == "interrupted":
 session_status = AgentSession.Status.SUSPENDED
 else:
 session_status = AgentSession.Status.ERROR
 await AgentSession.objects.filter(id=agent_session.id).aupdate(
 status=session_status,
 final_answer=final_content,
 updated_at=timezone.now,
 )
 except Exception:
 logger.exception(
 "agent_session_finalize_failed",
 conversation_id=str(conversation.id),
 session_id=session_id,
 )
 # 2. 构建消息 metadata
 msg_metadata: dict[str, Any] = {
 "session_id": session_id,
 "model": model,
 "status": result_metadata.get("status", "unknown"),
 }
 if result_metadata.get("cost_usd"):
 msg_metadata["cost_usd"] = result_metadata["cost_usd"]
 if result_metadata.get("input_tokens"):
 msg_metadata["input_tokens"] = result_metadata["input_tokens"]
 if result_metadata.get("output_tokens"):
 msg_metadata["output_tokens"] = result_metadata["output_tokens"]
 if accumulated_thinking:
 msg_metadata["thinking"] = "".join(accumulated_thinking)
 tool_calls_data = tool_calls or None
 # 3. 保存 assistant 消息（幂等）
 if not await Message.objects.filter(id=assistant_msg_id).aexists:
 await Message.objects.acreate(
 id=assistant_msg_id,
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content=final_content,
 tool_calls=tool_calls_data,
 metadata=msg_metadata,
 )
 # 4. 更新对话时间
 await Conversation.objects.filter(id=conversation.id).aupdate(
 updated_at=timezone.now,
 )
 # 5. 标题生成
 if await should_generate_title(str(conversation.id)):
 title = await generate_title(str(conversation.id), user_message)
 if title and publish_title_event:
 final_events.append(
 AgentEvent(
 type=TITLE_GENERATED,
 data={"title": title},
 )
 )
 logger.info(
 "stream_message_sent",
 conversation_id=str(conversation.id),
 session_id=session_id,
 status=result_metadata.get("status", "unknown"),
 )
 # 6. Push 通知（deep_analysis 完成时）
 if result_metadata.get("deep_analysis"):
 try:
 from chat.push_service import ChatPushService
 await ChatPushService.anotify_deep_analysis_complete(
 user_id=notification_user_id,
 conversation_id=str(conversation.id),
 conversation_title=conversation.title,
 answer_preview=final_content,
 )
 except Exception as push_exc:
 try:
 logger.warning(
 "deep_analysis_push_notify_failed",
 conversation_id=str(conversation.id),
 session_id=session_id,
 error=str(push_exc),
 )
 except Exception:
 pass
 return final_events
