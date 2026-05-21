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
 parts: list[dict[str, Any]] | None = None,
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
 # 0. 用户主动中断已经把 DB 写成 INTERRUPTED：runner 在 cancel 之前如果已经
 # 跑完了 stream（race 窗口），graph 仍会正常走到 finalize；这里如果无条件用
 # result_metadata.status 覆盖，就把 ChatInterruptView 写的 INTERRUPTED 抹掉
 # 了 —— 前端刷新看到 status=completed，与"已停止"的 UI 心智不符。
 # 真源是 DB 已落库的 INTERRUPTED，不是后到的 graph 终态。
 interrupted_by_user = False
 try:
 latest_status = await Conversation.objects.filter(
 id=conversation.id,
 ).values_list("status", flat=True).afirst
 interrupted_by_user = latest_status == Conversation.Status.INTERRUPTED
 except Exception:
 logger.warning(
 "finalize_status_reload_failed",
 conversation_id=str(conversation.id),
 exc_info=True,
 )
 # 1. 更新 AgentSession 最终状态
 try:
 status_str = result_metadata.get("status", "unknown")
 if interrupted_by_user:
 status_str = "interrupted"
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
 # Quick Task：落库强同源
 # 来源 chat_runner 路径（parts 非空）→ 用 PartsCollector 派生的 content +
 # tool_calls 覆盖入参（确保三者一致，无第二事实源；PLAN §3.4）。
 # legacy 路径（parts 为空 / None）→ 沿用旧 final_content + tool_calls 入参
 # （兼容 deep_analysis BarrierManager 回灌路径，那条路径不走 chat_runner
 # collector，见 PLAN §D4）。
 parts_data: list[dict[str, Any]] = list(parts or )
 if parts_data:
 try:
 from chat.parts import PartsCollector
 collector = PartsCollector
 collector.parts = parts_data
 derived = collector.to_message_payload
 final_content = derived["content"]
 tool_calls_data = derived["tool_calls"] or None
 except Exception:
 logger.warning(
 "finalize_parts_derive_failed",
 conversation_id=str(conversation.id),
 exc_info=True,
 )
 msg_metadata["parts_schema_version"] = 1
 # 3. 保存/更新 assistant 消息（幂等 — barrier 多次 resume 时更新为终态）
 existing = await Message.objects.filter(id=assistant_msg_id).afirst
 if existing:
 await Message.objects.filter(id=assistant_msg_id).aupdate(
 content=final_content,
 tool_calls=tool_calls_data,
 metadata=msg_metadata,
 parts=parts_data,
 )
 else:
 await Message.objects.acreate(
 id=assistant_msg_id,
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content=final_content,
 tool_calls=tool_calls_data,
 metadata=msg_metadata,
 parts=parts_data,
 )
 # 4. 更新对话时间 + 终态
 if status_str == "completed":
 conv_status = Conversation.Status.COMPLETED
 elif status_str == "interrupted":
 conv_status = Conversation.Status.INTERRUPTED
 else:
 conv_status = Conversation.Status.ERROR
 # exclude(INTERRUPTED) 双保险：即使第 0 步 reload 撞 race 没拿到最新值，
 # 也不会把后到的 graph 完成态写回去抹掉用户的「停止」操作。
 await Conversation.objects.filter(
 id=conversation.id,
 ).exclude(status=Conversation.Status.INTERRUPTED).aupdate(
 status=conv_status,
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
