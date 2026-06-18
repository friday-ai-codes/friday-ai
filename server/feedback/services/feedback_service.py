"""反馈领域服务：创建、回复（触发站内信）、状态流转。

写库统一经本服务。管理员回复 / 状态变更会通过 ``NotificationService.create_and_push``
给反馈提交者发站内信，正文为 markdown，并带 ``/feedback?id=<feedback_id>`` 跳转链接。
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from feedback.models import Feedback, FeedbackReply
from notifications.models import Notification
from notifications.services import NotificationService

# 状态进入这些值时记录 resolved_at
_RESOLVED_STATES = {Feedback.Status.RESOLVED, Feedback.Status.CLOSED, Feedback.Status.WONT_FIX}

_STATUS_LABELS = dict(Feedback.Status.choices)


def _feedback_link(feedback_id: Any) -> str:
    # 「我的反馈」已并入消息中心；旧链接 /feedback?id= 由前端重定向兼容
    return f"/notifications?tab=feedback&fid={feedback_id}"


class FeedbackService:
    """用户反馈领域服务。"""

    @staticmethod
    async def create_feedback(
        *,
        user_id: Any,
        category: str,
        content: str,
        title: str = "",
        attachments: list[dict[str, Any]] | None = None,
        page_url: str = "",
        conversation_id: Any = None,
        message_id: Any = None,
    ) -> Feedback:
        """创建一条用户反馈。"""
        return await Feedback.objects.acreate(
            created_by_id=user_id,
            category=category,
            title=title or "",
            content=content,
            attachments=attachments or [],
            page_url=page_url or "",
            conversation_id=conversation_id,
            message_id=message_id,
        )

    @staticmethod
    async def add_admin_reply(
        *,
        feedback: Feedback,
        author_id: Any,
        author_repr: str,
        content: str,
    ) -> FeedbackReply:
        """管理员回复反馈，并给提交者发站内信。"""
        reply = await FeedbackReply.objects.acreate(
            feedback=feedback,
            author_id=author_id,
            author_repr=author_repr,
            content=content,
            is_admin=True,
        )
        # 触发反馈的 updated_at 刷新
        await Feedback.objects.filter(id=feedback.id).aupdate(updated_at=timezone.now())

        await NotificationService.create_and_push(
            recipient_id=feedback.created_by_id,
            type=Notification.Type.FEEDBACK_REPLY,
            title=f"您的反馈有新回复：{feedback.title or '反馈'}",
            body=content,
            link=_feedback_link(feedback.id),
            metadata={"feedback_id": str(feedback.id), "reply_id": str(reply.id)},
        )
        return reply

    @staticmethod
    async def update_status(
        *,
        feedback: Feedback,
        status: str,
        notify: bool = True,
    ) -> Feedback:
        """变更反馈状态，可选给提交者发状态变更站内信。"""
        feedback.status = status
        update_fields = ["status", "updated_at"]
        if status in _RESOLVED_STATES and feedback.resolved_at is None:
            feedback.resolved_at = timezone.now()
            update_fields.append("resolved_at")
        feedback.updated_at = timezone.now()
        await feedback.asave(update_fields=update_fields)

        if notify:
            label = _STATUS_LABELS.get(status, status)
            await NotificationService.create_and_push(
                recipient_id=feedback.created_by_id,
                type=Notification.Type.FEEDBACK_STATUS,
                title=f"反馈状态更新为「{label}」：{feedback.title or '反馈'}",
                body=f"您的反馈状态已更新为 **{label}**。",
                link=_feedback_link(feedback.id),
                metadata={"feedback_id": str(feedback.id), "status": status},
            )
        return feedback
