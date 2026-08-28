"""IDE 会话问答 Capture 账本模型（STORE-01~05）。

模型层不提供业务 create/save 方法；所有写入收口于
``initiatives.services.CaptureService``（INV-6，由 ``test_capture_inv6_guard`` 守护）。
"""

from __future__ import annotations

import uuid

from django.db import models


class SessionCaptureStatus(models.TextChoices):
    """Capture 从持久化到评估、入图的状态。"""

    PENDING_EVAL = "pending_eval", "待评估"
    EVAL_FAILED = "eval_failed", "评估失败"
    INGEST_PENDING = "ingest_pending", "待入图"
    EVALUATED = "evaluated", "已评估"


class SessionCapture(models.Model):
    """独立会话 Capture 账本；业务写入只能经 CaptureService。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_captures",
        verbose_name="项目",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="session_captures",
        verbose_name="仓库",
    )
    question = models.TextField(verbose_name="问题（已脱敏）")
    answer = models.TextField(verbose_name="可见答案精华（已脱敏）")
    response_model = models.CharField(max_length=128, default="unknown", verbose_name="响应模型")
    provider = models.CharField(max_length=64, default="unknown", verbose_name="模型供应商")
    input_tokens = models.CharField(max_length=64, default="unknown", verbose_name="输入 token")
    output_tokens = models.CharField(max_length=64, default="unknown", verbose_name="输出 token")
    session_id = models.CharField(max_length=255, verbose_name="会话标识")
    question_hash = models.CharField(max_length=64, verbose_name="规范化问题哈希")
    link_reason = models.CharField(max_length=64, verbose_name="挂钩结果")
    branch_name = models.CharField(max_length=255, blank=True, default="", verbose_name="分支")
    initiated_by_user_id = models.CharField(
        max_length=64, blank=True, default="system", verbose_name="触发用户"
    )
    status = models.CharField(
        max_length=20,
        choices=SessionCaptureStatus.choices,
        default=SessionCaptureStatus.PENDING_EVAL,
        verbose_name="状态",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_session_captures"
        verbose_name = "会话 Capture"
        verbose_name_plural = "会话 Captures"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["initiated_by_user_id", "session_id", "question_hash"],
                name="uniq_session_capture_user_session_question",
            ),
        ]
        indexes = [
            models.Index(fields=["initiated_by_user_id", "session_id"]),
            models.Index(fields=["repository", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"SessionCapture({self.id}, {self.status})"
