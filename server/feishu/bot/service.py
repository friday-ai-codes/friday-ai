"""Feishu bot orchestration service."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from django.utils import timezone

from agents.core.events import MESSAGE_COMPLETE, PHASE_TRANSITION, TEXT_DELTA, TOOL_USE_START
from chat.conversation_service import ConversationService, extract_reference_summaries
from chat.models import Message
from chat.multimodal import (
    MAX_IMAGES_PER_MESSAGE,
    ImageValidationError,
    build_image_part,
    store_image_bytes,
)
from chat.parts import TextPart, part_to_dict
from feishu.cards.bot_cards import (
    build_answer_card,
    build_answer_markdown,
    build_background_analysis_card,
    build_clarification_card,
    build_error_card,
    build_streaming_card,
    build_streaming_card_v2,
    build_thinking_card,
    build_welcome_card,
)
from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus
from projects.models import Project
from services.feishu_im import FeishuIMError, FeishuIMService

from .parser import extract_message_attachments
from .project_resolver import ProjectResolver
from .thread_resolver import ThreadResolver, attach_message_to_thread

logger = structlog.get_logger(__name__)

_GROUP_CONTEXT_MSG_LIMIT = 500
WAITING_FINAL_ANSWER_POLL_ATTEMPTS = 10
WAITING_FINAL_ANSWER_POLL_INTERVAL_SECONDS = 1.0

# CardKit 流式增量推送节流阈值（秒）：合并 ~300ms 内的 TEXT_DELTA，
# 控制单卡写频率在飞书 10QPS 内（P-3）。测试可 patch 为 0 关闭节流。
_CARDKIT_STREAM_THROTTLE_S = 0.3


@dataclass(slots=True)
class _CardKitStream:
    """CardKit 流式卡片本轮会话态：card_id/element_id/message_id + 单调 sequence。

    sequence 由 content PUT 与 settle 共享同一计数器（P-2），每次写前 +1、起始得 1，
    保证飞书侧严格递增（否则触发 300317）。
    """

    card_id: str
    element_id: str
    message_id: str
    sequence: int = 0

    def next_sequence(self) -> int:
        """返回下一个严格递增的 sequence（写前 +1，起始 1）。"""
        self.sequence += 1
        return self.sequence


def _build_cardkit_closeout_card() -> dict[str, Any]:
    """CardKit 流式成功后用于收口「思考中」卡的简洁终态卡（W-1）。

    绝不复用 build_streaming_card([])（那渲染「思考中...」会留一张永久悬挂的旧卡）。
    """
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Friday"},
            "template": "blue",
            "ud_icon": {"tag": "standard_icon", "token": "ai-sparkle_outlined"},
        },
        "elements": [
            {"tag": "markdown", "content": "已回复，请见下方卡片 👇"},
        ],
    }

_AUTO_MATCH_PROJECT_REASONS = {
    "explicit_alias_match",
    "thread_project_reuse",
    "recent_project_preference",
}


def _build_group_context(history_items: list[dict[str, Any]]) -> str:
    """将飞书群聊历史消息格式化为 LLM 可读的上下文字符串。"""
    if not history_items:
        return ""

    lines: list[str] = []
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
        if text.strip():
            lines.append(f"[{sender_id}]: {text.strip()}")

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
        self.thread_resolver = thread_resolver or ThreadResolver()
        self.project_resolver = project_resolver or ProjectResolver()

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
            card=build_thinking_card(),
        )
        message.processing_card_message_id = thinking_card_id
        await message.asave(update_fields=["processing_card_message_id"])
        thread.last_processing_card_id = thinking_card_id
        await thread.asave(update_fields=["last_processing_card_id", "updated_at"])

        try:
            image_attachments = self._image_attachments(message)
            default_image_prompt = "请分析这张图片"
            display_question = message.normalized_text or (
                default_image_prompt if image_attachments else "附件消息"
            )

            if self._needs_attachment_clarification(message):
                await self._send_clarification(
                    im_service,
                    thread,
                    question=display_question,
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
                            question=display_question,
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
                    title=self._build_conversation_title(display_question),
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

            llm_content = message.normalized_text or (
                default_image_prompt if image_attachments else ""
            )
            if group_context:
                llm_content = group_context + "当前用户的问题：\n" + llm_content

            try:
                input_parts = await self._build_input_parts(
                    im_service=im_service,
                    message=message,
                    text=llm_content,
                    image_attachments=image_attachments,
                )
            except (FeishuIMError, ImageValidationError) as exc:
                metadata = thread.metadata or {}
                metadata["last_image_error"] = str(exc)
                if isinstance(exc, ImageValidationError):
                    metadata["last_image_error_code"] = exc.code
                error_card = build_error_card(
                    question=display_question,
                    hint_text=(
                        "图片下载或校验失败，请确认机器人有权限读取该消息资源，"
                        "或重新发送一张 PNG/JPEG/GIF/WebP 图片。"
                    ),
                )
                await self._replace_card(
                    im_service,
                    chat_id=message.chat_id,
                    card_message_id=thinking_card_id,
                    card=error_card,
                )
                thread.metadata = metadata
                await thread.asave(update_fields=["metadata", "updated_at"])
                return {"status": "error", "error": "image_download_failed"}

            # 流式消费 send_message_stream()，实时更新卡片显示工具调用
            session_id = ""
            final_answer = ""
            usage: dict[str, Any] = {}
            cost_usd: float = 0
            tool_names: list[str] = []
            last_run_phase = ""
            last_run_id = ""
            waiting_task_count = 0
            stream_started_at = timezone.now()

            # CardKit 流式正文态（D-2 惰性创建 + fail-soft 降级）：
            # 首个 TEXT_DELTA 才创建实体；任一步失败置 cardkit_disabled 切回既有 PATCH 路径。
            cardkit: _CardKitStream | None = None
            cardkit_disabled = False
            cardkit_done = False
            body = ""
            last_push_at = 0.0
            element_id = "md_body"

            async for event in ConversationService.send_message_stream(
                conversation_id=str(thread.conversation_id),
                content=llm_content,
                role="developer",
                project_context_line=project_context_line,
                input_parts=input_parts,
            ):
                if event.type == TOOL_USE_START:
                    tool_name = str(event.data.get("tool_name") or "")
                    if tool_name and tool_name not in tool_names:
                        tool_names.append(tool_name)
                        await im_service.update_card(
                            thinking_card_id,
                            build_streaming_card(tool_names),
                        )
                elif event.type == TEXT_DELTA:
                    # P-1：流式正文只消费 TEXT_DELTA，绝不读 PART_DELTA（双轨共存否则正文翻倍）。
                    delta = str(event.data.get("text") or "")
                    if not delta:
                        continue
                    body += delta  # P-4：累积全量正文
                    # D-2 惰性创建：首个有效 TEXT_DELTA 才建 CardKit 实体并下发。
                    if cardkit is None and not cardkit_disabled:
                        try:
                            cid = await im_service.create_card_entity(
                                build_streaming_card_v2(element_id=element_id),
                                uuid=uuid.uuid4().hex,
                            )
                            mid = await im_service.send_card_entity(
                                receive_id=message.chat_id,
                                receive_id_type="chat_id",
                                card_id=cid,
                            )
                            cardkit = _CardKitStream(
                                card_id=cid,
                                element_id=element_id,
                                message_id=mid,
                            )
                        except Exception:
                            logger.warning(
                                "feishu_cardkit_create_failed",
                                chat_id=message.chat_id,
                                exc_info=True,
                            )
                            cardkit = None
                            cardkit_disabled = True
                    # P-3 节流推送：合并 ~300ms 内的 delta，content 全量（P-4）、sequence 单调（P-2）。
                    if cardkit is not None:
                        now = time.monotonic()
                        if now - last_push_at >= _CARDKIT_STREAM_THROTTLE_S:
                            try:
                                await im_service.stream_card_content(
                                    card_id=cardkit.card_id,
                                    element_id=cardkit.element_id,
                                    content=body,
                                    sequence=cardkit.next_sequence(),
                                    uuid=uuid.uuid4().hex,
                                )
                                last_push_at = now
                            except Exception:
                                logger.warning(
                                    "feishu_cardkit_stream_failed",
                                    chat_id=message.chat_id,
                                    card_id=cardkit.card_id,
                                    exc_info=True,
                                )
                                cardkit = None
                                cardkit_disabled = True
                elif event.type == PHASE_TRANSITION:
                    last_run_phase = str(event.data.get("phase") or last_run_phase)
                    last_run_id = str(event.data.get("run_id") or last_run_id)
                    session_id = str(event.data.get("session_id") or session_id)
                    raw_task_count = event.data.get("blocking_task_count") or event.data.get("task_count") or 0
                    try:
                        waiting_task_count = int(raw_task_count)
                    except (TypeError, ValueError):
                        waiting_task_count = 0
                elif event.type == MESSAGE_COMPLETE:
                    session_id = event.data.get("session_id", "")
                    raw_answer = event.data.get("final_answer") or event.data.get("result") or ""
                    final_answer = str(raw_answer).strip()
                    usage = event.data.get("usage") or {}
                    cost_usd = event.data.get("cost_usd", 0)

            metadata = thread.metadata or {}
            if last_run_phase:
                metadata["last_run_phase"] = last_run_phase
            if last_run_id:
                metadata["last_run_id"] = last_run_id
            if waiting_task_count:
                metadata["last_waiting_task_count"] = waiting_task_count
            if session_id:
                metadata["last_session_id"] = session_id

            if not final_answer and last_run_phase == "waiting":
                metadata["last_waiting_started_at"] = timezone.now().isoformat()
                fallback_answer = await self._poll_final_answer_from_conversation(
                    str(thread.conversation_id),
                    created_after=stream_started_at,
                )
                if fallback_answer:
                    final_answer = fallback_answer
                    metadata["last_waiting_fallback_status"] = "resolved"
                else:
                    metadata["last_waiting_fallback_status"] = "timeout"
                    waiting_card = build_background_analysis_card(
                        question=display_question,
                        task_count=waiting_task_count,
                        phase=last_run_phase,
                    )
                    await self._replace_card(
                        im_service,
                        chat_id=message.chat_id,
                        card_message_id=thinking_card_id,
                        card=waiting_card,
                    )
                    thread.status = FeishuBotThreadStatus.ACTIVE
                    thread.metadata = metadata
                    await thread.asave(update_fields=["status", "metadata", "updated_at"])
                    return {"status": "waiting", "session_id": session_id}

            if not final_answer:
                metadata["last_empty_completion"] = True
                error_card = build_error_card(
                    question=display_question,
                    hint_text="本次没有生成最终回复。请稍后重试，或补充项目/仓库与问题上下文。",
                )
                await self._replace_card(
                    im_service,
                    chat_id=message.chat_id,
                    card_message_id=thinking_card_id,
                    card=error_card,
                )
                thread.metadata = metadata
                await thread.asave(update_fields=["metadata", "updated_at"])
                return {"status": "error", "error": "empty_final_answer", "session_id": session_id}

            references = await extract_reference_summaries(session_id)
            usage_info: dict[str, Any] | None = None
            if usage or cost_usd:
                usage_info = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cost_usd": cost_usd,
                }

            # D-3 终态：CardKit 可用且有正文 → 推终态全量 markdown + settle 收尾 + 收口 thinking 卡。
            if cardkit is not None:
                content_delivered = False
                try:
                    final_md = build_answer_markdown(
                        final_answer,
                        references,
                        usage_info,
                        matched_space_label,
                    )
                    await im_service.stream_card_content(
                        card_id=cardkit.card_id,
                        element_id=cardkit.element_id,
                        content=final_md,
                        sequence=cardkit.next_sequence(),
                        uuid=uuid.uuid4().hex,
                    )
                    content_delivered = True  # 答案已在 CardKit 卡渲染（W-2 判定依据）
                    # W-1：先收口 thinking 卡，绝不留「思考中」悬挂（即便 settle 失败也不悬挂）。
                    await self._replace_card(
                        im_service,
                        chat_id=message.chat_id,
                        card_message_id=thinking_card_id,
                        card=_build_cardkit_closeout_card(),
                    )
                    await im_service.settle_card_stream(
                        card_id=cardkit.card_id,
                        sequence=cardkit.next_sequence(),
                        uuid=uuid.uuid4().hex,
                    )
                    thread.last_bot_message_id = cardkit.message_id
                    cardkit_done = True
                except Exception:
                    if content_delivered:
                        # W-2：内容已送达，仅 settle 失败 → 仅 warning 视为 answered，
                        # 不再补发 build_answer_card（避免答案重复两次）。
                        logger.warning(
                            "feishu_cardkit_settle_failed",
                            chat_id=message.chat_id,
                            card_id=cardkit.card_id,
                            exc_info=True,
                        )
                        thread.last_bot_message_id = cardkit.message_id
                        cardkit_done = True
                    else:
                        # 内容推送阶段失败 → 完全降级回既有 build_answer_card 路径。
                        logger.warning(
                            "feishu_cardkit_stream_failed",
                            chat_id=message.chat_id,
                            card_id=cardkit.card_id,
                            exc_info=True,
                        )
                        cardkit_done = False

            if not cardkit_done:
                # 降级兜底（P-9）：CardKit 未启用/中途失效/终态内容推送失败 → 既有路径，答案/引用/usage 不丢。
                answer_card = build_answer_card(
                    question=display_question,
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
            metadata["last_reference_count"] = len(references)
            metadata["last_session_id"] = session_id
            metadata["chat_type"] = message.chat_type
            thread.metadata = metadata
            await thread.asave(update_fields=["last_bot_message_id", "status", "metadata", "updated_at"])
            return {"status": "answered", "session_id": session_id}
        except ImageValidationError as exc:
            logger.warning("feishu_bot_vision_not_supported", message_id=message.message_id, error=str(exc))
            error_card = build_error_card(
                question=message.normalized_text or "图片消息",
                hint_text=exc.message,
            )
            await self._replace_card(
                im_service,
                chat_id=message.chat_id,
                card_message_id=thinking_card_id,
                card=error_card,
            )
            metadata = thread.metadata or {}
            metadata["last_error"] = exc.message
            metadata["last_error_code"] = exc.code
            thread.metadata = metadata
            await thread.asave(update_fields=["metadata", "updated_at"])
            return {"status": "error", "error": exc.code}
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
        if FeishuBotService._image_attachments(message):
            return False
        return not bool((message.normalized_text or "").strip())

    @staticmethod
    def _image_attachments(message: FeishuBotMessage) -> list[dict[str, Any]]:
        attachments = extract_message_attachments(message.raw_payload or {})
        images: list[dict[str, Any]] = []
        for attachment in attachments:
            tag = str(attachment.get("tag") or "")
            image_key = str(attachment.get("image_key") or "")
            if tag in {"image", "img"} and image_key:
                images.append(attachment)
        return images[:MAX_IMAGES_PER_MESSAGE]

    @staticmethod
    async def _build_input_parts(
        *,
        im_service: FeishuIMService,
        message: FeishuBotMessage,
        text: str,
        image_attachments: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        if not image_attachments:
            return None

        parts: list[dict[str, Any]] = [
            part_to_dict(
                TextPart(
                    id=f"p_{uuid.uuid4().hex[:12]}",
                    index=0,
                    text=text,
                    state="done",
                )
            )
        ]
        for idx, attachment in enumerate(image_attachments, start=1):
            image_key = str(attachment.get("image_key") or "")
            if not image_key:
                raise ImageValidationError("missing_image_key", "图片资源缺少 image_key，无法下载。")
            resource = await im_service.download_message_resource(
                message_id=message.message_id,
                file_key=image_key,
                resource_type="image",
            )
            stored = store_image_bytes(
                resource.content,
                declared_mime_type=resource.mime_type,
                source=f"feishu:{message.message_id}:{image_key}",
                filename=str(attachment.get("name") or image_key),
            )
            parts.append(
                build_image_part(
                    index=idx,
                    mime_type=stored.mime_type,
                    size_bytes=stored.size_bytes,
                    storage_ref=stored.storage_ref,
                    alt_text=str(attachment.get("name") or ""),
                )
            )
        return parts

    @staticmethod
    async def _maybe_send_welcome(im_service: FeishuIMService, thread: FeishuBotThread) -> None:
        has_previous_thread = await FeishuBotThread.objects.filter(chat_id=thread.chat_id).exclude(pk=thread.pk).aexists()
        if has_previous_thread:
            return
        welcome_id = await im_service.send_card(
            receive_id=thread.chat_id,
            receive_id_type="chat_id",
            card=build_welcome_card(),
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
        return (project.feishu_project_key or project.name or "未命名空间").strip()

    @staticmethod
    async def _fetch_group_context_history(
        im_service: FeishuIMService,
        chat_id: str,
    ) -> list[dict[str, Any]]:
        if not hasattr(im_service, "get_chat_history"):
            return []
        return await im_service.get_chat_history(chat_id, page_size=50, max_messages=_GROUP_CONTEXT_MSG_LIMIT)

    @staticmethod
    async def _poll_final_answer_from_conversation(conversation_id: str, *, created_after: datetime) -> str:
        for _ in range(WAITING_FINAL_ANSWER_POLL_ATTEMPTS):
            answer = await FeishuBotService._latest_assistant_answer(conversation_id, created_after=created_after)
            if answer:
                return answer
            if WAITING_FINAL_ANSWER_POLL_INTERVAL_SECONDS > 0:
                await asyncio.sleep(WAITING_FINAL_ANSWER_POLL_INTERVAL_SECONDS)
        return ""

    @staticmethod
    async def _latest_assistant_answer(conversation_id: str, *, created_after: datetime) -> str:
        queryset = (
            Message.objects.filter(
                conversation_id=conversation_id,
                role=Message.Role.ASSISTANT,
                created_at__gte=created_after,
            )
            .exclude(content="")
            .order_by("-created_at")
        )
        async for message in queryset[:5]:
            content = (message.content or "").strip()
            if content:
                return content
        return ""

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
        question = (question or "新问题").strip()
        return question[:40] if question else "新问题"
