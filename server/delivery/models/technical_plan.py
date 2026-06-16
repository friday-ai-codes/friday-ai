"""canonical 方案脊柱模型（DOMAIN §5.1 / §12.7，PLAN-01 模型位）。

立方案唯一事实源的落库底座：

- **``TechnicalPlan``**：方案操作态实体；``content`` 真身由版本承载，``current_version``
  指向当前 ``PlanVersion``；``origin`` 区分来源（chat/mcp/workflow/orchestration），
  ``work_item`` 可空（INV-2：chat 自然语言需求无脊柱时 null + origin=chat 即"自然语言需求"，
  不另设 bool）。
- **``PlanVersion``**：方案版本（§7 ``MergedPlan`` schema 存 ``content``）；版本链经
  ``supersedes`` self FK + ``unique_together(plan, version)`` 强制版本唯一。
- **``PlanExternalRef``**：workflow 软链承载表（DOMAIN §5.2）——chat/mcp 用各自旧表的
  ``canonical_plan_id`` 字段软链，workflow 无独立旧表，用本映射表
  （``external_ref`` 形如 ``workflow:{execution_id}:{node_id}``）承载软链。

循环 FK（``TechnicalPlan.current_version`` ↔ ``PlanVersion.plan``）经字符串前向引用 +
nullable 处理，单 migration 建表后由 service 写入（对齐 ``Document.current_version``）。

落库/版本/关联只经 delivery ``TechnicalPlanService``（INV-6）；本模型层**不写**任何
create/save/版本管理业务方法。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class TechnicalPlanOrigin(models.TextChoices):
    """方案来源枚举（DOMAIN §12.7）。"""

    CHAT = "chat", "对话"
    MCP = "mcp", "MCP"
    WORKFLOW = "workflow", "工作流"
    ORCHESTRATION = "orchestration", "编排"


class TechnicalPlanStatus(models.TextChoices):
    """方案生命周期状态枚举（DOMAIN §5.4）。"""

    DRAFT = "draft", "草稿"
    UNDER_REVIEW = "under_review", "评审中"
    APPROVED = "approved", "已批准"
    SUPERSEDED = "superseded", "已替换"
    ARCHIVED = "archived", "已归档"


class TechnicalPlan(models.Model):
    """canonical 方案操作态实体（方案唯一事实源，DOMAIN §5.1 / §12.7）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # INV-2：方案可追溯 WorkItem；chat 自然语言需求无脊柱时 null（null + origin=chat
    # 即"自然语言需求"，不另设 bool）。SET_NULL 避免删 WorkItem 抹方案。
    work_item = models.ForeignKey(
        WorkItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="technical_plans",
    )
    origin = models.CharField(
        max_length=16,
        choices=TechnicalPlanOrigin.choices,
    )
    # 前向字符串引用 + related_name="+" 避免与 PlanVersion.plan 反查名冲突，处理循环 FK；
    # SET_NULL 避免删版本抹方案（对齐 Document.current_version）。
    current_version = models.ForeignKey(
        "delivery.PlanVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=TechnicalPlanStatus.choices,
        default=TechnicalPlanStatus.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_technical_plan"
        verbose_name = "技术方案"
        verbose_name_plural = "技术方案"
        indexes = [
            models.Index(fields=["work_item"]),
            models.Index(fields=["origin", "status"]),
        ]

    def __str__(self) -> str:
        return f"TechnicalPlan({self.id}, {self.origin}/{self.status})"


class PlanVersion(models.Model):
    """方案版本（§7 MergedPlan schema 存 content，版本链经 supersedes，DOMAIN §12.7）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(
        TechnicalPlan,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    # 被本版本取代的旧版本；SET_NULL 与 §12.7 "supersedes FK(self,null)" 对齐。
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    # §7 MergedPlan schema：title/summary/api_contracts/dependency_dag/data_migrations/
    # compat_risks/release_order/rollback_plan/execution_plan——校验/版本逻辑归 service。
    content = models.JSONField(default=dict)
    # sha256 hex；内容相等不翻版本（v0.3/v0.6 铁律），由 service 本地计算（不 import knowledge，INV-3）。
    content_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_plan_version"
        verbose_name = "方案版本"
        verbose_name_plural = "方案版本"
        unique_together = (("plan", "version"),)
        indexes = [
            models.Index(fields=["plan", "-version"]),
        ]

    def __str__(self) -> str:
        return f"{self.plan_id}:v{self.version}"


class PlanExternalRef(models.Model):
    """workflow 软链承载表（DOMAIN §5.2）。

    chat/mcp 用各自旧表的 ``canonical_plan_id`` 字段软链；workflow 无独立旧表，
    用本映射表承载——``external_ref`` 形如 ``workflow:{execution_id}:{node_id}``，
    唯一定位一个 canonical ``TechnicalPlan``。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_ref = models.CharField(max_length=255, unique=True, db_index=True)
    canonical = models.ForeignKey(
        TechnicalPlan,
        on_delete=models.CASCADE,
        related_name="external_refs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_plan_external_ref"
        verbose_name = "方案外部软链"
        verbose_name_plural = "方案外部软链"

    def __str__(self) -> str:
        return f"PlanExternalRef({self.external_ref} -> {self.canonical_id})"
