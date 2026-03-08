"""Feishu bot orchestration service."""
from __future__ import annotations
from typing import Any
import structlog
from chat.conversation_service import ConversationService, extract_reference_summaries
from feishu.cards.bot_cards import (
 build_answer_card,
 build_clarification_card,
 build_error_card,
 build_processing_card,
 build_welcome_card,
)
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from services.feishu_im import FeishuIMService
from .project_resolver import ProjectResolver
from .thread_resolver import ThreadResolver, attach_message_to_thread
logger = structlog.get_logger(__name__)
class FeishuBotService:
 """Process accepted Feishu bot messages end-to-end."""
 def __init__(
 self,
 *,
 thread_resolver: ThreadResolver | None = None,
 project_resolver: ProjectResolver | None = None,
 ):
 self.thread_resolver = thread_resolver or ThreadResolver
 self.project_resolver = project_resolver or ProjectResolver
 async def process_message(self, message_id: str) -> dict[str, Any]:
 message = await FeishuBotMessage.objects.select_related(
 "thread",
 "thread__project",
 "thread__conversation",
 ).aget(message_id=message_id)
 thread = message.thread
 if thread is None:
 thread = await FeishuBotThread.objects.acreate(
 chat_id=message.chat_id,
 root_message_id=message.message_id,
 last_user_message_id=message.message_id,
 )
 message.thread = thread
 await message.asave(update_fields=["thread"])
 im_service = await FeishuIMService.create(thread.project)
 await self._maybe_send_welcome(im_service, thread)
 processing_card_id = await im_service.send_card(
 receive_id=message.chat_id,
 receive_id_type="chat_id",
 card=build_processing_card(message.normalized_text or "附件消息", progress_state="项目识别中"),
 )
 message.processing_card_message_id = processing_card_id
 await message.asave(update_fields=["processing_card_message_id"])
 thread.last_processing_card_id = processing_card_id
 await thread.asave(update_fields=["last_processing_card_id", "updated_at"])
 try:
 if self._needs_attachment_clarification(message):
 await self._send_clarification(
 im_service,
 thread,
 question=message.normalized_text or "附件消息",
 candidates=["请补充文字描述", "请补充项目或仓库名称"],
 status=FeishuBotThreadStatus.AWAITING_PROJECT_CLARIFICATION,
 reason="attachment_without_text",
 )
 return {"status": "clarification", "reason": "attachment_without_text"}
 thread_resolution = await self.thread_resolver.resolve(message)
 if thread_resolution.thread is not None:
 thread = thread_resolution.thread
 await attach_message_to_thread(message, thread)
 if thread_resolution.status == "awaiting_topic_clarification":
 await self._send_clarification(
 im_service,
 thread,
 question=message.normalized_text,
 candidates=["回复“新问题：...”", "或引用旧消息继续追问"],
 status=FeishuBotThreadStatus.AWAITING_TOPIC_CLARIFICATION,
 reason=thread_resolution.reason,
 )
 return {"status": "clarification", "reason": thread_resolution.reason}
 project_resolution = await self.project_resolver.resolve(message, thread)
 if project_resolution.status != "resolved" or project_resolution.project is None:
 await self._send_clarification(
 im_service,
 thread,
 question=message.normalized_text,
 candidates=project_resolution.candidates,
 status=FeishuBotThreadStatus.AWAITING_PROJECT_CLARIFICATION,
 reason=project_resolution.reason,
 )
 return {"status": "clarification", "reason": project_resolution.reason}
 thread.project = project_resolution.project
 if thread.conversation_id is None:
 conversation = await ConversationService.create_conversation(
 project_id=str(project_resolution.project.id),
 title=self._build_conversation_title(message.normalized_text),
 )
 thread.conversation = conversation
 await thread.asave(update_fields=["project", "conversation", "updated_at"])
 result = await ConversationService.send_message(
 conversation_id=str(thread.conversation_id),
 content=message.normalized_text,
 role="developer",
 )
 references = await extract_reference_summaries(result.get("session_id", ""))
 answer_content = result["message"].content
 answer_card = build_answer_card(
 question=message.normalized_text,
 answer=answer_content,
 references=references,
 )
 updated = await im_service.update_card(processing_card_id, answer_card)
 if updated:
 thread.last_bot_message_id = processing_card_id
 else:
 thread.last_bot_message_id = await im_service.send_card(
 receive_id=message.chat_id,
 receive_id_type="chat_id",
 card=answer_card,
 )
 logger.warning(
 "feishu_bot_processing_card_update_failed",
 message_id=message.message_id,
 processing_card_id=processing_card_id,
 )
 thread.status = FeishuBotThreadStatus.ACTIVE
 metadata = thread.metadata or {}
 metadata["last_reference_count"] = len(references)
 metadata["last_session_id"] = result.get("session_id", "")
 thread.metadata = metadata
 await thread.asave(update_fields=["last_bot_message_id", "status", "metadata", "updated_at"])
 return {"status": "answered", "session_id": result.get("session_id", "")}
 except Exception as exc:
 logger.exception("feishu_bot_processing_failed", message_id=message.message_id, error=str(exc))
 await im_service.send_card(
 receive_id=message.chat_id,
 receive_id_type="chat_id",
 card=build_error_card(
 question=message.normalized_text or "附件消息",
 hint_text="请稍后重试，并补充项目/仓库信息；若持续失败请联系管理员。",
 ),
 )
 metadata = thread.metadata or {}
 metadata["last_error"] = str(exc)
 thread.metadata = metadata
 await thread.asave(update_fields=["metadata", "updated_at"])
 return {"status": "error", "error": str(exc)}
 @staticmethod
 def _needs_attachment_clarification(message: FeishuBotMessage) -> bool:
 if message.message_type not in {"image", "file", "audio", "post"}:
 return False
 return not bool((message.normalized_text or "").strip)
 @staticmethod
 async def _maybe_send_welcome(im_service: FeishuIMService, thread: FeishuBotThread) -> None:
 has_previous_thread = await FeishuBotThread.objects.filter(chat_id=thread.chat_id).exclude(pk=thread.pk).aexists
 if has_previous_thread:
 return
 welcome_id = await im_service.send_card(
 receive_id=thread.chat_id,
 receive_id_type="chat_id",
 card=build_welcome_card,
 )
 thread.last_bot_message_id = welcome_id
 metadata = thread.metadata or {}
 metadata["welcome_sent"] = True
 thread.metadata = metadata
 await thread.asave(update_fields=["last_bot_message_id", "metadata", "updated_at"])
 @staticmethod
 async def _send_clarification(
 im_service: FeishuIMService,
 thread: FeishuBotThread,
 *,
 question: str,
 candidates: list[str],
 status: str,
 reason: str,
 ) -> None:
 card_id = await im_service.send_card(
 receive_id=thread.chat_id,
 receive_id_type="chat_id",
 card=build_clarification_card(question=question, candidates=candidates),
 )
 metadata = thread.metadata or {}
 metadata["clarification_reason"] = reason
 metadata["clarification_candidates"] = candidates
 thread.status = status
 thread.last_bot_message_id = card_id
 thread.metadata = metadata
 await thread.asave(update_fields=["status", "last_bot_message_id", "metadata", "updated_at"])
 @staticmethod
 def _build_conversation_title(question: str) -> str:
 question = (question or "新问题").strip
 return question[:40] if question else "新问题"
