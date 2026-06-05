"""WebhookConfig and WebhookLog model definitions."""

import hashlib
import hmac
import uuid

from django.db import models


class WebhookConfig(models.Model):
    """Webhook 配置

    用于配置外部系统回调 Friday 的 webhook。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="webhook_configs",
    )

    name = models.CharField(max_length=200, verbose_name="名称")
    description = models.TextField(blank=True, default="")

    # Webhook 路径（自动生成或自定义）
    path = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="路径",
        help_text="Webhook URL 的路径部分",
    )

    # 安全配置
    secret = models.CharField(
        max_length=200,
        blank=True,
        default="",
        verbose_name="签名密钥",
    )
    allowed_ips = models.JSONField(
        default=list,
        blank=True,
        verbose_name="允许的 IP",
    )

    # 状态
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_webhook_configs"
        verbose_name = "Webhook 配置"
        verbose_name_plural = "Webhook 配置"

    def __str__(self) -> str:
        return f"{self.name} ({self.workflow.name})"

    def get_full_url(self) -> str:
        """获取完整的 webhook URL"""
        from django.conf import settings

        base_url = getattr(settings, "FRIDAY_BASE_URL", "http://localhost:8000")
        return f"{base_url}/api/workflows/webhooks/{self.path}/"

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """验证请求签名"""
        if not self.secret:
            return True

        expected = hmac.new(
            self.secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(f"sha256={expected}", signature)


class WebhookLog(models.Model):
    """Webhook 调用日志"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    webhook_config = models.ForeignKey(
        WebhookConfig,
        on_delete=models.CASCADE,
        related_name="logs",
    )

    # 请求信息
    request_method = models.CharField(max_length=10)
    request_headers = models.JSONField(default=dict)
    request_body = models.TextField(blank=True, default="")
    request_ip = models.GenericIPAddressField(null=True, blank=True)

    # 响应信息
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, default="")

    # 关联的执行
    execution = models.ForeignKey(
        "workflows.WorkflowExecution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_logs",
    )

    # 状态
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workflow_webhook_logs"
        verbose_name = "Webhook 日志"
        verbose_name_plural = "Webhook 日志"
        ordering = ["-created_at"]
