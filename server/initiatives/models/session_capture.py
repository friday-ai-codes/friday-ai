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
    EVALUATING = "evaluating", "评估中"
    EVAL_FAILED = "eval_failed", "评估失败"
    EVALUATED_LOW = "evaluated_low", "低价值已评估"
    INGEST_PENDING = "ingest_pending", "待入图"
    INGESTING = "ingesting", "入图中"
    INGESTED = "ingested", "已入图"
    INGEST_FAILED = "ingest_failed", "入图失败"
    # 兼容历史或手工写入的数据；新状态机不得写入或 claim 此状态。
    EVALUATED = "evaluated", "已评估"


class SessionCaptureValueTier(models.TextChoices):
    """Capture 评估价值档位闭集。"""

    HIGH = "high", "高"
    MEDIUM = "medium", "中"
    LOW = "low", "低"


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
    value_tier = models.CharField(
        max_length=6,
        choices=SessionCaptureValueTier.choices,
        blank=True,
        default="",
        verbose_name="价值档位",
    )
    distilled_essence = models.TextField(blank=True, default="", verbose_name="评估精华")
    eval_attempts = models.PositiveIntegerField(default=0, verbose_name="评估尝试次数")
    ingest_attempts = models.PositiveIntegerField(default=0, verbose_name="入图尝试次数")
    last_error = models.TextField(blank=True, default="", verbose_name="最近错误（已脱敏）")
    next_retry_at = models.DateTimeField(null=True, blank=True, verbose_name="下次重试时间")
    evaluated_at = models.DateTimeField(null=True, blank=True, verbose_name="评估完成时间")
    ingested_at = models.DateTimeField(null=True, blank=True, verbose_name="入图完成时间")
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
            models.Index(fields=["status", "next_retry_at"]),
        ]

    def __str__(self) -> str:
        return f"SessionCapture({self.id}, {self.status})"
