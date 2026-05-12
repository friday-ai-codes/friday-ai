"""Feishu bot orchestration service."""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any
import structlog
from agents.core.events import MESSAGE_COMPLETE, TOOL_USE_START
from chat.conversation_service import ConversationService, extract_reference_summaries
from feishu.cards.bot_cards import (
 build_answer_card,
 build_clarification_card,
 build_error_card,
 build_streaming_card,
 build_thinking_card,
 build_welcome_card,
)
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from projects.models import Project
from services.feishu_im import FeishuIMService
from .project_resolver import ProjectResolver
from .thread_resolver import ThreadResolver, attach_message_to_thread
logger = structlog.get_logger(__name__)
_GROUP_CONTEXT_MSG_LIMIT = 500
_AUTO_MATCH_PROJECT_REASONS = {
 "explicit_alias_match",
 "thread_project_reuse",
 "recent_project_preference",
}
def _build_group_context(history_items: list[dict[str, Any]]) -> str:
 """将飞书群聊历史消息格式化为 LLM 可读的上下文字符串。"""
 if not history_items:
 return ""
 lines: list[str] =
 for item in reversed(history_items):
 sender = item.get("sender", {})
 sender_type = sender.get("sender_type", "")
 if sender_type == "app":
 continue
 sender_id = sender.get("id", "unknown")
 body = item.get("body", {})
 content_str = body.get("content", "")
 try:
 content = json.loads(content_str) if isinstance(content_str, str) else content_str
 except (json.JSONDecodeError, TypeError):
 content = {"text": str(content_str)}
 text = content.get("text", "") if isinstance(content, dict) else str(content)
 if text.strip:
 lines.append(f"[{sender_id}]: {text.strip}")
 if not lines:
 return ""
 return (
 "以下是群聊中的近期消息（仅供参考，不要主动回答其他人的问题）：\n"
 "---\n"
 + "\n".join(lines)
 + "\n---\n\n"
 )
@dataclass(slots=True)
class ProjectContextDecision:
 project: Project
 matched_space_label: str = ""
 project_context_line: str | None = None
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
 is_p2p = message.chat_type == "p2p"
 im_service = await FeishuIMService.create(thread.project)
 if not is_p2p:
 await self._maybe_send_welcome(im_service, thread)
 # 立即发送「思考中...」卡片
 thinking_card_id = await im_service.send_card(
 receive_id=message.chat_id,
 receive_id_type="chat_id",
 card=build_thinking_card,
 )
 message.processing_card_message_id = thinking_card_id
 await message.asave(update_fields=["processing_card_message_id"])
 thread.last_processing_card_id = thinking_card_id
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
 if is_p2p:
 project_context = await self._resolve_p2p_project_context(message, thread)
 if project_context is None:
 await self._replace_card(
 im_service,
 chat_id=message.chat_id,
 card_message_id=thinking_card_id,
 card=build_error_card(
 question=message.normalized_text or "附件消息",
 hint_text="当前没有可用项目可供私聊上下文使用，请先创建或关联项目。",
 ),
 )
 return {"status": "error", "error": "no_project_for_p2p"}
 thread.project = project_context.project
 matched_space_label = project_context.matched_space_label
 project_context_line = project_context.project_context_line
 else:
 thread_resolution = await self.thread_resolver.resolve(message)
 if thread_resolution.thread is not None:
 thread = thread_resolution.thread
 await attach_message_to_thread(message, thread)
 if thread_resolution.status == "awaiting_topic_clarification":
 await self._send_clarification(
 im_service,
 thread,
 question=message.normalized_text,
 candidates=["回复「新问题:...」", "或引用旧消息继续追问"],
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
 matched_space_label = self._space_label(project_resolution.project)
 project_context_line = (
 f"当前已自动匹配「{matched_space_label}」空间（对应项目：{project_resolution.project.name}）"
 )
 if thread.conversation_id is None:
 conversation = await ConversationService.create_conversation(
 space_id=str(thread.project_id),
 title=self._build_conversation_title(message.normalized_text),
 )
 thread.conversation = conversation
 await thread.asave(update_fields=["project", "conversation", "updated_at"])
 # 群聊模式：获取群聊历史作为上下文
 group_context = ""
 if not is_p2p:
 try:
 history = await self._fetch_group_context_history(im_service, message.chat_id)
 group_context = _build_group_context(history)
 except Exception:
 logger.warning("group_context_fetch_failed", chat_id=message.chat_id, exc_info=True)
 llm_content = message.normalized_text
 if group_context:
 llm_content = group_context + "当前用户的问题：\n" + message.normalized_text
 # 流式消费 send_message_stream，实时更新卡片显示工具调用
 session_id = ""
 final_answer = ""
 usage: dict[str, Any] = {}
 cost_usd: float = 0
 tool_names: list[str] =
 async for event in ConversationService.send_message_stream(
 conversation_id=str(thread.conversation_id),
 content=llm_content,
 role="developer",
 project_context_line=project_context_line,
 ):
 if event.type == TOOL_USE_START:
 tool_name = str(event.data.get("tool_name") or "")
 if tool_name and tool_name not in tool_names:
 tool_names.append(tool_name)
 await im_service.update_card(
 thinking_card_id,
 build_streaming_card(tool_names),
 )
 elif event.type == MESSAGE_COMPLETE:
 session_id = event.data.get("session_id", "")
 final_answer = event.data.get("final_answer", "")
 usage = event.data.get("usage") or {}
 cost_usd = event.data.get("cost_usd", 0)
 references = await extract_reference_summaries(session_id)
 usage_info: dict[str, Any] | None = None
 if usage or cost_usd:
 usage_info = {
 "input_tokens": usage.get("input_tokens", 0),
 "output_tokens": usage.get("output_tokens", 0),
 "cost_usd": cost_usd,
 }
 answer_card = build_answer_card(
 question=message.normalized_text,
 answer=final_answer,
 references=references,
 usage=usage_info,
 compact=is_p2p,
 matched_space_label=matched_space_label,
 )
 thread.last_bot_message_id = await self._replace_card(
 im_service,
 chat_id=message.chat_id,
 card_message_id=thinking_card_id,
 card=answer_card,
 )
 thread.status = FeishuBotThreadStatus.ACTIVE
 metadata = thread.metadata or {}
 metadata["last_reference_count"] = len(references)
 metadata["last_session_id"] = session_id
 metadata["chat_type"] = message.chat_type
 thread.metadata = metadata
 await thread.asave(update_fields=["last_bot_message_id", "status", "metadata", "updated_at"])
 return {"status": "answered", "session_id": session_id}
 except Exception as exc:
 logger.exception("feishu_bot_processing_failed", message_id=message.message_id, error=str(exc))
 error_card = build_error_card(
 question=message.normalized_text or "附件消息",
 hint_text="请稍后重试，并补充项目/仓库信息；若持续失败请联系管理员。",
 )
 await self._replace_card(
 im_service,
 chat_id=message.chat_id,
 card_message_id=thinking_card_id,
 card=error_card,
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
 async def _resolve_p2p_project_context(
 self,
 message: FeishuBotMessage,
 thread: FeishuBotThread,
 ) -> ProjectContextDecision | None:
 """私聊模式尽量直接可聊，不再因为歧义进入澄清卡。"""
 if thread.project_id and thread.project is not None:
 label = self._space_label(thread.project)
 return ProjectContextDecision(
 project=thread.project,
 matched_space_label=label,
 project_context_line=f"当前已自动匹配「{label}」空间（对应项目：{thread.project.name}）",
 )
 project_resolution = await self.project_resolver.resolve(message, thread)
 if project_resolution.project is not None:
 if project_resolution.reason in _AUTO_MATCH_PROJECT_REASONS:
 label = self._space_label(project_resolution.project)
 return ProjectContextDecision(
 project=project_resolution.project,
 matched_space_label=label,
 project_context_line=(
 f"当前已自动匹配「{label}」空间（对应项目：{project_resolution.project.name}）"
 ),
 )
 return ProjectContextDecision(
 project=project_resolution.project,
 matched_space_label="",
 project_context_line="",
 )
 projects = [project async for project in Project.objects.order_by("-updated_at", "-created_at")]
 if not projects:
 return None
 return ProjectContextDecision(
 project=projects[0],
 matched_space_label="",
 project_context_line="",
 )
 @staticmethod
 def _space_label(project: Project) -> str:
 return (project.feishu_project_key or project.name or "未命名空间").strip
 @staticmethod
 async def _fetch_group_context_history(
 im_service: FeishuIMService,
 chat_id: str,
 ) -> list[dict[str, Any]]:
 if not hasattr(im_service, "get_chat_history"):
 return
 return await im_service.get_chat_history(chat_id, page_size=50, max_messages=_GROUP_CONTEXT_MSG_LIMIT)
 @staticmethod
 async def _replace_card(
 im_service: FeishuIMService,
 *,
 chat_id: str,
 card_message_id: str,
 card: dict[str, Any],
 ) -> str:
 updated = False
 try:
 updated = await im_service.update_card(card_message_id, card)
 except Exception:
 logger.warning("feishu_bot_card_update_exception", card_id=card_message_id, exc_info=True)
 if updated:
 return card_message_id
 logger.warning("feishu_bot_card_update_failed", card_id=card_message_id)
 return await im_service.send_card(
 receive_id=chat_id,
 receive_id_type="chat_id",
 card=card,
 )
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
