"""Feishu models for webhook logs and bot conversation state."""

import uuid
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from workflows.models.execution import WorkflowExecution


class TriggerLogStatus(models.TextChoices):
    """Trigger log status choices."""

    ACCEPTED = "accepted", "已接受"
    IGNORED = "ignored", "已忽略"
    ERROR = "error", "错误"
    DUPLICATE = "duplicate", "重复"


class FeishuBotThreadStatus(models.TextChoices):
    """Feishu bot thread lifecycle."""

    ACTIVE = "active", "进行中"
    AWAITING_PROJECT_CLARIFICATION = "awaiting_project_clarification", "待澄清项目"
    AWAITING_TOPIC_CLARIFICATION = "awaiting_topic_clarification", "待澄清话题"
    CLOSED = "closed", "已关闭"


class TriggerLog(models.Model):
    """Unified log for Feishu webhook triggers and work item details.

    Combines the functionality of WebhookLog and WorkItemLog into a single
    model that tracks the complete event processing chain.
    """

    # 反向关系类型声明
    workflow_executions: "QuerySet[WorkflowExecution]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Space reference (use string reference to avoid circular import)
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trigger_logs",
    )
    project_key = models.CharField(max_length=100, blank=True, null=True)

    # Webhook event info
    event_uuid = models.CharField(max_length=100, blank=True, null=True, unique=True)
    event_type = models.CharField(max_length=100, blank=True, default="")
    webhook_raw_request = models.TextField(blank=True, default="")

    # Work item info
    work_item_id = models.CharField(max_length=50, blank=True, null=True)
    work_item_type = models.CharField(max_length=50, blank=True, default="")
    work_item_name = models.CharField(max_length=500, blank=True, default="")
    work_item_raw_response = models.TextField(blank=True, default="")

    # Extracted key fields for display
    prd_url = models.URLField(max_length=1000, blank=True, default="")
    description = models.TextField(blank=True, default="")
    tech_doc_url = models.URLField(max_length=1000, blank=True, default="")

    # Status
    status = models.CharField(
        max_length=20,
        choices=TriggerLogStatus.choices,
        default=TriggerLogStatus.ACCEPTED,
    )
    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trigger_logs"
        verbose_name = "触发日志"
        verbose_name_plural = "触发日志"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} - {self.work_item_name or self.work_item_id}"


class FeishuBotThread(models.Model):
    """Persistent state for a bot conversation thread inside a Feishu chat."""

    chat_id = models.CharField(max_length=128, db_index=True)
    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feishu_bot_threads",
    )
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feishu_bot_threads",
    )
    status = models.CharField(
        max_length=40,
        choices=FeishuBotThreadStatus.choices,
        default=FeishuBotThreadStatus.ACTIVE,
    )
    root_message_id = models.CharField(max_length=128, blank=True, default="")
    last_user_message_id = models.CharField(max_length=128, blank=True, default="")
    last_bot_message_id = models.CharField(max_length=128, blank=True, default="")
    last_processing_card_id = models.CharField(max_length=128, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "feishu_bot_threads"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["chat_id", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.chat_id}:{self.status}"


class FeishuBotMessage(models.Model):
    """Inbound Feishu messages normalized for bot processing."""

    message_id = models.CharField(max_length=128, unique=True)
    thread = models.ForeignKey(
        FeishuBotThread,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
    )
    chat_id = models.CharField(max_length=128, db_index=True)
    chat_type = models.CharField(max_length=16, blank=True, default="group")
    sender_open_id = models.CharField(max_length=128, blank=True, default="")
    message_type = models.CharField(max_length=32)
    normalized_text = models.TextField(blank=True, default="")
    quote_message_id = models.CharField(max_length=128, blank=True, default="")
    mentioned_bot = models.BooleanField(default=False)
    processing_card_message_id = models.CharField(max_length=128, blank=True, default="")
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feishu_bot_messages"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["chat_id", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.message_id


class FeishuBindingSource(models.TextChoices):
    """飞书人员↔Friday 用户绑定来源（IDENT-01）。"""

    MANUAL = "manual", "手动绑定"
    JIT = "jit", "飞书事件自动绑定"


class FeishuUserBinding(models.Model):
    """飞书人员（user_key/open_id）↔ Friday ``User`` 映射（IDENT-01）。

    多对多语义：一个飞书人可对多 Friday 账号、反之亦然（常态一对一）。``source`` 区分手动
    绑定与飞书事件 JIT 自动绑定；``(feishu_user_key, user)`` 唯一。写入收口于
    ``feishu.services.identity``（``bind_feishu_user``），解析经单一入口 ``resolve_feishu_user``
    （手动优先，未映射 fail-soft 返回 None）。**绝不**把飞书凭证写日志（脱敏规范）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feishu_user_key = models.CharField(
        max_length=100, blank=True, default="", db_index=True, verbose_name="飞书 user_key"
    )
    open_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True, verbose_name="飞书 open_id"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feishu_bindings",
        verbose_name="Friday 用户",
    )
    source = models.CharField(
        max_length=20,
        choices=FeishuBindingSource.choices,
        default=FeishuBindingSource.MANUAL,
        verbose_name="绑定来源",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "feishu_user_bindings"
        verbose_name = "飞书人员绑定"
        verbose_name_plural = "飞书人员绑定"
        constraints = [
            models.UniqueConstraint(
                fields=["feishu_user_key", "user"],
                condition=~models.Q(feishu_user_key=""),
                name="uniq_feishu_user_key_binding",
            ),
            models.UniqueConstraint(
                fields=["open_id", "user"],
                condition=~models.Q(open_id=""),
                name="uniq_feishu_open_id_binding",
            ),
        ]
        indexes = [
            models.Index(fields=["feishu_user_key"]),
            models.Index(fields=["open_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.feishu_user_key or self.open_id} -> {self.user_id} ({self.source})"


class ProcessedEvent(models.Model):
    """飞书事件幂等去重记录。

    使用 DB 唯一约束替代内存 set，确保多进程部署和服务重启后幂等性不丢失。
    """

    event_id = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feishu_processed_events"
        verbose_name = "已处理事件"
        verbose_name_plural = "已处理事件"

    def __str__(self) -> str:
        return self.event_id


# Key field constants for extracting from work item fields.
# 唯一事实源在 Django-free 的 services.feishu_parsing（避免 services→models 层级倒置）；
# 此处反向 import 复用，保持既有 KeyFields.* 调用方向后兼容。
from services.feishu_parsing import (  # noqa: E402
    DESCRIPTION_FIELD_KEY,
    PRD_URL_FIELD_KEY,
    TECH_DOC_URL_FIELD_KEY,
)


class KeyFields:
    """Key field identifiers for work item fields."""

    PRD_URL = PRD_URL_FIELD_KEY  # 需求文档链接 field_bcff9b
    DESCRIPTION = DESCRIPTION_FIELD_KEY  # 需求描述
    TECH_DOC_URL = TECH_DOC_URL_FIELD_KEY  # 技术方案文档链接 field_3f6667
