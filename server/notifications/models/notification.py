"""Notification：通用站内信通知模型。

为反馈回复/状态变更、工作流完成、系统公告等场景提供统一的「收件人 + 标题 +
markdown 正文 + 跳转链接 + 已读态」存储契约。正文 ``body`` 存原始 markdown，由前端
实时渲染。``link`` 为前端路由（如 ``/feedback?id=<uuid>``），点击后跳转。
"""

import uuid

from django.db import models


class Notification(models.Model):
    """站内信通知（表 ``notification``）。"""

    class Type(models.TextChoices):
        FEEDBACK_REPLY = "feedback_reply", "反馈回复"
        FEEDBACK_STATUS = "feedback_status", "反馈状态变更"
        SYSTEM = "system", "系统通知"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 收件人；删用户级联删除其通知
    recipient = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    # 通知类型（开放 CharField，不强制 DB 枚举，便于未来扩展）
    type = models.CharField(max_length=32, default=Type.SYSTEM, db_index=True)

    title = models.CharField(max_length=255)
    # markdown 正文（前端实时渲染）
    body = models.TextField(blank=True, default="")
    # 前端跳转路径（如 /feedback?id=<uuid>）
    link = models.CharField(max_length=512, blank=True, default="")
    # 附加上下文（feedback_id / reply_id / status 等）
    metadata = models.JSONField(default=dict, blank=True)

    # 已读时间（null = 未读）
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        verbose_name = "站内信通知"
        verbose_name_plural = "站内信通知"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["recipient", "-created_at"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __str__(self) -> str:
        return f"Notification({self.type}, to={self.recipient_id})"
