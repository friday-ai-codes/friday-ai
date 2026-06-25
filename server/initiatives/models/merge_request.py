"""MergeRequest 实体模型（MR-01/02）。

把此前散落的 MR/PR url 字符串（``CodingTask.pr_url`` / ``CodingSession.pr_url`` /
``McpCodingExecutionTrace.mr_result``）升级为**独立实体** —— 关联项目/仓库/工作项，记
url + 源·目标分支 + 状态(open/merged/closed) + review 状态 + 平台 + 外部 id。

- ``MergeRequest``：当前态 MR 实体（幂等键 ``(platform, repository, external_id)``）。
- ``MergeRequestEvent``：**append-only** 入站 webhook 事件留痕（脱敏后 raw payload + 幂等
  ``dedup_key``）。

模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.MergeRequestService``（INV-6，由 ``test_merge_request_inv6_guard`` 守护）。
"""

from __future__ import annotations

import uuid

from django.db import models


class MRPlatform(models.TextChoices):
    """MR/PR 来源平台。"""

    GITHUB = "github", "GitHub"
    GITLAB = "gitlab", "GitLab"


class MRStatus(models.TextChoices):
    """MR/PR 状态（可扩展闭集）。"""

    OPEN = "open", "打开"
    MERGED = "merged", "已合并"
    CLOSED = "closed", "已关闭"


class MergeRequest(models.Model):
    """MR/PR 独立实体（MR-01）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merge_requests",
        verbose_name="项目",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merge_requests",
        verbose_name="仓库",
    )
    work_item = models.ForeignKey(
        "delivery.WorkItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merge_requests",
        verbose_name="工作项",
    )
    platform = models.CharField(
        max_length=20, choices=MRPlatform.choices, verbose_name="平台"
    )
    external_id = models.CharField(
        max_length=100, blank=True, default="", verbose_name="平台外部 id（PR/MR 编号）"
    )
    url = models.URLField(max_length=1000, blank=True, default="", verbose_name="MR/PR 链接")
    title = models.CharField(max_length=500, blank=True, default="", verbose_name="标题")
    source_branch = models.CharField(
        max_length=255, blank=True, default="", verbose_name="源分支"
    )
    target_branch = models.CharField(
        max_length=255, blank=True, default="", verbose_name="目标分支"
    )
    status = models.CharField(
        max_length=20,
        choices=MRStatus.choices,
        default=MRStatus.OPEN,
        verbose_name="状态",
    )
    review_status = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name="review 状态",
        help_text="如 approved/changes_requested/commented（平台原值归一）",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_merge_requests"
        verbose_name = "Merge Request"
        verbose_name_plural = "Merge Requests"
        ordering = ["-created_at"]
        constraints = [
            # 幂等键：external_id 非空时 (platform, repository, external_id) 唯一。
            models.UniqueConstraint(
                fields=["platform", "repository", "external_id"],
                condition=~models.Q(external_id=""),
                name="uniq_mr_platform_repo_external",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["platform", "external_id"]),
        ]

    def __str__(self) -> str:
        return f"MR({self.platform}:{self.external_id}, {self.status})"


class MergeRequestEvent(models.Model):
    """入站 webhook 事件留痕（append-only，幂等 dedup + 脱敏 raw payload，MR-02）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merge_request = models.ForeignKey(
        "initiatives.MergeRequest",
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="MR 实体",
    )
    event_type = models.CharField(max_length=64, verbose_name="事件类型")
    # 幂等去重键：platform:external_id:event_type:action[:delivery] 等组合，唯一。
    dedup_key = models.CharField(
        max_length=255, unique=True, verbose_name="幂等去重键"
    )
    # 原始 payload（写库前已 redact_for_ledger，绝不落明文凭证）。
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name="脱敏原始 payload")
    initiated_by_user_id = models.CharField(
        max_length=64, blank=True, default="system", verbose_name="触发用户"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "initiative_merge_request_events"
        verbose_name = "MR 事件"
        verbose_name_plural = "MR 事件"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merge_request", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"MREvent({self.merge_request_id}, {self.event_type})"
