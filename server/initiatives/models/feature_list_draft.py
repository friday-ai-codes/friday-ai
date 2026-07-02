"""feature list 异步解析草稿（每项目一份）。

把"粘贴文档 → AI 分层解析（先出模块、再逐模块填功能点）"从「HTTP 请求内同步 await」
改为「durable 后台任务 + 并发模块解析 + 进度持久化」，解决：

- **刷新/关闭页面不丢**：解析进度与部分结果落库（``tree`` + ``progress`` + ``status``），
  重开弹窗按项目取回草稿续看。
- **多项目不互相阻塞**：起解析只是 defer 一个后台作业立即返回，受统一并发上限调度。
- **草稿保存**：用户手工编辑的未确认 feature list 也存这里（``status`` 非 committed 即草稿）。

commit 后（写入正式 ``Artifact``）即删除本草稿——每项目仅一份，不堆积。进度经 channels
``apush_project_event(project_id, "feature_list_draft", ...)`` 实时推前端。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class FeatureListDraftStatus(models.TextChoices):
    """草稿解析状态机。"""

    IDLE = "idle", "空闲"
    PARSING = "parsing", "解析中"
    PARTIAL = "partial", "部分完成"
    READY = "ready", "解析完成（待确认）"
    FAILED = "failed", "解析失败"


class FeatureListDraftPhase(models.TextChoices):
    """解析阶段（用于进度权重与前端提示）。"""

    IDLE = "idle", "未开始"
    MODULES = "modules", "解析模块中"
    FEATURES = "features", "逐功能点解析中"
    DONE = "done", "已完成"


class FeatureListDraft(models.Model):
    """项目 feature list 解析草稿（每项目唯一，OneToOne）。

    ``tree`` 形态（与手动录入 modules 同构，附解析元信息）：
    ``{"modules": [{"module": str, "summary": str, "line_start": int, "line_end": int,
       "parse_state": "pending|running|done|failed",
       "features": [{"name": str, "acceptance": [str], "source": str}]}]}``。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.OneToOneField(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="feature_list_draft",
        verbose_name="项目",
    )
    status = models.CharField(
        max_length=16,
        choices=FeatureListDraftStatus.choices,
        default=FeatureListDraftStatus.IDLE,
        verbose_name="状态",
    )
    phase = models.CharField(
        max_length=16,
        choices=FeatureListDraftPhase.choices,
        default=FeatureListDraftPhase.IDLE,
        verbose_name="阶段",
    )
    progress = models.PositiveSmallIntegerField(default=0, verbose_name="进度百分比")
    source_text = models.TextField(
        blank=True,
        default="",
        verbose_name="原文",
        help_text="粘贴/取回的原始文档，供模块任务按行号切片、断点续跑",
    )
    tree = models.JSONField(default=dict, blank=True, verbose_name="解析树")
    error = models.TextField(blank=True, default="", verbose_name="失败原因（脱敏）")
    job_id = models.CharField(max_length=200, blank=True, default="", verbose_name="作业标识")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="最近操作人",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_feature_list_drafts"
        verbose_name = "Feature List 草稿"
        verbose_name_plural = "Feature List 草稿"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"FeatureListDraft(project={self.project_id}, status={self.status})"
