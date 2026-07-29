"""通用 Artifact 脊柱模型（Chassis v2 · P1）。

把"演进中的交付物"从方案专用（TechnicalPlan/PlanVersion）泛化为 type 化的一等
对象，使需求评审报告 / 故事点估算 / 缺陷修复方案 等未来 process 复用同一事实源：

- ``Artifact``：交付物操作态实体；``artifact_type`` 区分种类（technical_plan |
  review_report | ...，注册式开放枚举见 ``delivery.artifacts.registry``），``content``
  真身由版本承载，``current_version`` 指向当前 ``ArtifactVersion``。
- ``ArtifactVersion``：版本（``content`` 形状由 artifact_type 注册 schema 决定），
  版本链经 ``supersedes`` self FK + ``unique_together(artifact, version_no)``；
  ``content_hash`` 内容相等不翻版本。

落库/版本/关联只经 ``ArtifactService``（单一写入入口）；本模型层不写业务方法。

> P2 会把 ``produced_by_session_id`` 升级为指向 ``ConvergenceSession`` 的 FK；P1
> 阶段先用字符串软引用，避免对尚未建立的 process runtime 形成构建期依赖。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class ArtifactStatus(models.TextChoices):
    """交付物生命周期状态。"""

    DRAFT = "draft", "草稿"
    UNDER_REVIEW = "under_review", "评审中"
    APPROVED = "approved", "已批准"
    SUPERSEDED = "superseded", "已替换"
    ARCHIVED = "archived", "已归档"


class ArtifactApprovalStatus(models.TextChoices):
    """版本审批状态。"""

    NONE = "none", "无"
    PENDING = "pending", "待审批"
    APPROVED = "approved", "已批准"
    REJECTED = "rejected", "已驳回"


class BlueprintStatus(models.TextChoices):
    """技术方案蓝图 11 态生命周期（Phase 111，DESIGN §4.2）。

    与 ``ArtifactStatus`` 正交（映射见 DESIGN §4.3）：``status`` 承载通用交付物
    生命周期，``blueprint_status`` 承载蓝图专属用户可见状态；空串 = 旧 v0 数据
    不参与状态机。
    """

    RESEARCHING = "researching", "调研中"
    DRAFTING = "drafting", "产出中"
    AI_REVIEWING = "ai_reviewing", "AI 审查中"
    NEEDS_CLARIFICATION = "needs_clarification", "需要澄清"
    PENDING_REVIEW = "pending_review", "待人类审查"
    CONFIRMED = "confirmed", "已确认"
    IMPLEMENTING = "implementing", "实施中"
    IMPLEMENTED = "implemented", "实施完成"
    ARCHIVED = "archived", "已归档"
    FAILED = "failed", "已失败"
    SUPERSEDED = "superseded", "已废弃"


class Artifact(models.Model):
    """通用交付物操作态实体（事实源）。"""

    objects: "models.Manager[Artifact]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 交付物种类（注册式开放枚举，见 delivery.artifacts.registry）。
    artifact_type = models.CharField(max_length=40, verbose_name="交付物类型")

    work_item = models.ForeignKey(
        WorkItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artifacts",
    )

    title = models.CharField(max_length=500, blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=ArtifactStatus.choices,
        default=ArtifactStatus.DRAFT,
    )

    # 循环 FK：current_version ↔ ArtifactVersion.artifact，前向字符串引用 + nullable。
    current_version = models.ForeignKey(
        "delivery.ArtifactVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    created_by_user_id = models.CharField(max_length=64, blank=True, default="")

    # 蓝图 11 态（Phase 111）：字段级唯一 writer = BlueprintLifecycleService（INV-6），
    # 与既有 ArtifactStatus 正交（映射见 DESIGN §4.3）；空串 = 旧 v0 数据不参与状态机。
    # max_length=32：needs_clarification 长 19 字符，照 16 截断（P5）。
    blueprint_status = models.CharField(
        max_length=32,
        choices=BlueprintStatus.choices,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_artifact"
        verbose_name = "交付物"
        verbose_name_plural = "交付物"
        indexes = [
            models.Index(fields=["artifact_type", "status"]),
            models.Index(fields=["work_item"]),
            models.Index(fields=["artifact_type", "blueprint_status"]),
        ]

    def __str__(self) -> str:
        return f"Artifact({self.id}, {self.artifact_type}/{self.status})"


class ArtifactVersion(models.Model):
    """交付物版本（content 形状由 artifact_type 注册 schema 决定）。"""

    objects: "models.Manager[ArtifactVersion]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(
        Artifact,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_no = models.PositiveIntegerField()
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    content = models.JSONField(default=dict)
    # sha256 hex；内容相等不翻版本（由 service 本地计算）。
    content_hash = models.CharField(max_length=64, blank=True, default="")

    # 产出来源（P2 升级为 ConvergenceSession FK）。
    produced_by_session_id = models.CharField(max_length=64, blank=True, default="")
    # 触发产出的 signal/event 引用，用于回答"为何变成这个版本"。
    produced_by_ref = models.CharField(max_length=255, blank=True, default="")

    approval_status = models.CharField(
        max_length=16,
        choices=ArtifactApprovalStatus.choices,
        default=ArtifactApprovalStatus.NONE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_artifact_version"
        verbose_name = "交付物版本"
        verbose_name_plural = "交付物版本"
        unique_together = (("artifact", "version_no"),)
        indexes = [
            models.Index(fields=["artifact", "-version_no"]),
            models.Index(fields=["content_hash"]),
        ]

    def __str__(self) -> str:
        return f"{self.artifact_id}:v{self.version_no}"
