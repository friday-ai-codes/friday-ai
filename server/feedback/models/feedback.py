"""Feedback / FeedbackReply：用户反馈与处理线程模型。

- ``Feedback``：用户提交的一条反馈（bug / 问题 / 功能建议 / 其他），正文存 markdown，
  附件以 JSON 列表存 ``storage_ref`` 引用（图片/视频，落 ``DATA_DIR/feedback_attachments``）。
  记录提交时所在页面 ``page_url``，以及（若在 AI 对话内）软引用的 ``conversation_id`` /
  ``message_id``（不建 FK，避免与 chat 硬耦合，对齐 PlanSession.conversation_id 范式）。
- ``FeedbackReply``：反馈处理线程的一条回复（管理员或用户），管理员回复会触发站内信。
"""

import uuid

from django.db import models


class Feedback(models.Model):
    """用户反馈（表 ``feedback``）。"""

    class Category(models.TextChoices):
        BUG = "bug", "Bug"
        QUESTION = "question", "问题"
        FEATURE = "feature", "功能建议"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        OPEN = "open", "待处理"
        IN_PROGRESS = "in_progress", "处理中"
        RESOLVED = "resolved", "已解决"
        CLOSED = "closed", "已关闭"
        WONT_FIX = "wont_fix", "不予处理"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 提交者；删用户级联删除其反馈
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="feedbacks",
        db_index=True,
    )

    category = models.CharField(max_length=16, default=Category.OTHER, db_index=True)
    title = models.CharField(max_length=255, blank=True, default="")
    # markdown 正文
    content = models.TextField()
    # 附件列表：[{storage_ref, kind: image|video, name, size, mime}]
    attachments = models.JSONField(default=list, blank=True)

    # 提交时所在页面（route.fullPath，含 query）
    page_url = models.CharField(max_length=1024, blank=True, default="")
    # AI 对话软引用（chat.Conversation.id / chat.Message.id，UUID），不建 FK
    conversation_id = models.UUIDField(null=True, blank=True, db_index=True)
    message_id = models.UUIDField(null=True, blank=True)

    status = models.CharField(max_length=16, default=Status.OPEN, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "feedback"
        verbose_name = "用户反馈"
        verbose_name_plural = "用户反馈"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["created_by", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Feedback({self.category}, {self.status}, by={self.created_by_id})"


class FeedbackReply(models.Model):
    """反馈处理线程的一条回复（表 ``feedback_reply``）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey(
        Feedback,
        on_delete=models.CASCADE,
        related_name="replies",
    )
    # 回复作者；删用户置空保留回复内容
    author = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_replies",
    )
    # 作者快照（删用户后仍可读）
    author_repr = models.CharField(max_length=255, blank=True, default="")
    # markdown 正文
    content = models.TextField()
    # 是否管理员回复（管理员回复触发站内信）
    is_admin = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback_reply"
        verbose_name = "反馈回复"
        verbose_name_plural = "反馈回复"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"FeedbackReply(feedback={self.feedback_id}, admin={self.is_admin})"
