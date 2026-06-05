"""Resolve whether an inbound bot message continues an existing thread."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from feishu.models import FeishuBotMessage, FeishuBotThread, FeishuBotThreadStatus

_EXPLICIT_NEW_PREFIXES = ("新问题", "新话题", "new question")
_FOLLOW_UP_MARKERS = (
    "那这个",
    "这个呢",
    "为什么",
    "继续",
    "然后呢",
    "那怎么办",
    "怎么修",
    "怎么改",
    "还有呢",
)


@dataclass(slots=True)
class ThreadResolution:
    status: str
    thread: FeishuBotThread | None
    reason: str


class ThreadResolver:
    """Resolve chat-level thread continuity."""

    async def resolve(self, message: FeishuBotMessage) -> ThreadResolution:
        text = (message.normalized_text or "").strip().lower()

        if self._is_explicit_new(text):
            return ThreadResolution(status="new", thread=message.thread, reason="explicit_new_prefix")

        if message.quote_message_id:
            quoted = await FeishuBotMessage.objects.select_related("thread").filter(
                message_id=message.quote_message_id
            ).afirst()
            if quoted and quoted.thread_id:
                return ThreadResolution(status="continue", thread=quoted.thread, reason="quoted_message")

        recent_threads = [
            thread async for thread in FeishuBotThread.objects.filter(chat_id=message.chat_id)
            .exclude(pk=message.thread_id or 0)
            .order_by("-updated_at")[:3]
        ]
        if not recent_threads:
            return ThreadResolution(status="new", thread=message.thread, reason="no_recent_thread")

        latest_thread = recent_threads[0]
        age = timezone.now() - latest_thread.updated_at
        if self._looks_like_follow_up(text) and age <= timedelta(hours=6):
            return ThreadResolution(status="continue", thread=latest_thread, reason="recent_follow_up")

        if age > timedelta(hours=6):
            return ThreadResolution(status="new", thread=message.thread, reason="last_thread_stale")

        if not text:
            return ThreadResolution(
                status="awaiting_topic_clarification",
                thread=latest_thread,
                reason="missing_text_context",
            )

        return ThreadResolution(
            status="awaiting_topic_clarification",
            thread=latest_thread,
            reason="ambiguous_topic_switch",
        )

    @staticmethod
    def _is_explicit_new(text: str) -> bool:
        return any(text.startswith(prefix) for prefix in _EXPLICIT_NEW_PREFIXES)

    @staticmethod
    def _looks_like_follow_up(text: str) -> bool:
        return any(text.startswith(prefix) for prefix in _FOLLOW_UP_MARKERS)


async def attach_message_to_thread(message: FeishuBotMessage, thread: FeishuBotThread) -> None:
    """Persist thread assignment for a message and keep thread activity fresh."""

    message.thread = thread
    await message.asave(update_fields=["thread"])
    thread.last_user_message_id = message.message_id
    if not thread.root_message_id:
        thread.root_message_id = message.message_id
    if thread.status == FeishuBotThreadStatus.CLOSED:
        thread.status = FeishuBotThreadStatus.ACTIVE
    await thread.asave(update_fields=["last_user_message_id", "root_message_id", "status", "updated_at"])
