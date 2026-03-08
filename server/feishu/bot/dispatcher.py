"""Shared dispatcher for inbound Feishu bot messages."""
from __future__ import annotations
from dataclasses import dataclass
import structlog
from django.db import IntegrityError
from agents.models import AgentSession
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from tasks.agent_tasks import schedule_resume_agent_session
from tasks.feishu_bot_tasks import schedule_process_feishu_bot_message
from .parser import InboundLarkMessage
logger = structlog.get_logger(__name__)
@dataclass(slots=True)
class DispatchResult:
 status: str
 reason: str = ""
 thread_id: int | None = None
 message_pk: int | None = None
async def _find_thread(message: InboundLarkMessage) -> FeishuBotThread | None:
 if message.quote_message_id:
 quoted = await FeishuBotMessage.objects.select_related("thread").filter(
 message_id=message.quote_message_id
 ).afirst
 if quoted and quoted.thread_id:
 return quoted.thread
 return await FeishuBotThread.objects.filter(chat_id=message.chat_id).order_by("-updated_at").afirst
async def _try_resume_suspended_agent(message: InboundLarkMessage) -> bool:
 if message.sender_is_bot or message.mentioned_bot or not message.normalized_text:
 return False
 session = await AgentSession.objects.filter(
 status=AgentSession.Status.SUSPENDED,
 temp_data__chat_id=message.chat_id,
 ).order_by("-updated_at").afirst
 if not session:
 return False
 schedule_resume_agent_session(session.session_id, message.normalized_text)
 logger.info(
 "feishu_message_resumed_agent",
 chat_id=message.chat_id,
 session_id=session.session_id,
 message_id=message.message_id,
 )
 return True
async def dispatch_inbound_message(message: InboundLarkMessage) -> DispatchResult:
 """Dispatch a normalized inbound message through the bot pipeline."""
 if await _try_resume_suspended_agent(message):
 return DispatchResult(status="resume_agent", reason="suspended_session")
 if message.sender_is_bot:
 return DispatchResult(status="ignored", reason="sender_is_bot")
 if message.chat_type and message.chat_type != "group":
 return DispatchResult(status="ignored", reason="unsupported_chat_type")
 if not message.mentioned_bot:
 return DispatchResult(status="ignored", reason="mention_required")
 if not message.has_effective_body:
 return DispatchResult(status="ignored", reason="empty_body")
 thread = await _find_thread(message)
 if thread is None:
 thread = await FeishuBotThread.objects.acreate(
 chat_id=message.chat_id,
 status=FeishuBotThreadStatus.ACTIVE,
 root_message_id=message.message_id,
 last_user_message_id=message.message_id,
 metadata={"source": "dispatcher"},
 )
 else:
 thread.last_user_message_id = message.message_id
 if not thread.root_message_id:
 thread.root_message_id = message.message_id
 await thread.asave(update_fields=["last_user_message_id", "root_message_id", "updated_at"])
 try:
 bot_message = await FeishuBotMessage.objects.acreate(
 message_id=message.message_id,
 thread=thread,
 chat_id=message.chat_id,
 sender_open_id=message.sender_open_id,
 message_type=message.message_type,
 normalized_text=message.normalized_text,
 quote_message_id=message.quote_message_id,
 mentioned_bot=message.mentioned_bot,
 raw_payload=message.raw_payload,
 )
 except IntegrityError:
 return DispatchResult(status="duplicate", reason="message_exists", thread_id=thread.pk)
 schedule_process_feishu_bot_message(message.message_id)
 logger.info(
 "feishu_bot_message_accepted",
 chat_id=message.chat_id,
 message_id=message.message_id,
 thread_id=thread.pk,
 )
 return DispatchResult(
 status="bot_message_accepted",
 thread_id=thread.pk,
 message_pk=bot_message.pk,
 )
