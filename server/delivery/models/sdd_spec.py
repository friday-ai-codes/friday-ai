"""SddSpec 脊柱实体（delivery app，Phase 49 SPEC-01/SPEC-02）。

立 v0.9 SDD spec「操作态脊柱」的数据底座——是 Phase 50（状态机流转 / 评审）、
Phase 51（编码前置 gate）、Phase 52（spec↔PR 关联 / 验收）的统一挂载点：

- **``SddSpec``**：每「方案版本 × SDD 仓」一份 openspec spec 操作态。``document`` FK
  持有 spec 正文/版本（SET_NULL：删文档不抹脊柱，对齐 delivery「删版本不抹脊柱」
  durability 范式）；``repository`` 指向被产 spec 的 SDD 仓（非空，幂等键之一）；
  ``work_item`` / ``plan_version`` 承载 SPEC-02 追溯（均可空——对齐 chat 自然语言
  需求无 work_item，INV-2）。

幂等键 ``unique_together(plan_version, repository)``：同一方案版本对同一仓只产一份
spec，重跑幂等不重复（DB 级约束 + SddSpecService 短路兜底）。

设计要点（守 INV-6 精神）：落库/状态变更**只经 ``SddSpecService``**（plan 02），本
模型层**不写**任何 create/save/状态变更业务方法（仅 ``__str__``）；旁路写表由 INV-6
grep 守护断言。跨 app FK（repositories.Repository）用字符串前向引用避免 import 环。
"""

import uuid

from django.db import models


class SddSpecStatus(models.TextChoices):
    """SddSpec spec 操作态全枚举（5 态，Phase 49 全定义，本 phase 仅落初值 draft）。

    刻意区别于 ``TechnicalPlanStatus``（``under_review`` / ``superseded``）——spec
    语义确需 ``in_review``（评审中）/ ``implemented``（已落地）态。状态流转逻辑归
    Phase 50，本 phase 不实现任何转移，只落 ``draft`` 初值。
    """

    DRAFT = "draft", "草稿"
    IN_REVIEW = "in_review", "评审中"
    APPROVED = "approved", "已批准"
    IMPLEMENTED = "implemented", "已落地"
    ARCHIVED = "archived", "已归档"


class SddSpecChangeKind(models.TextChoices):
    """spec 变更类型枚举：openspec change proposal vs spec delta。"""

    PROPOSAL = "proposal", "变更提案"
    DELTA = "delta", "规格增量"


class SddSpec(models.Model):
    """SDD spec 操作态脊柱（每「方案版本 × SDD 仓」一份，SPEC-01/SPEC-02）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 持有 spec 正文/版本；SET_NULL 保脊柱不随文档删除被抹（D-49-1）。
    document = models.ForeignKey(
        "delivery.Document",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sdd_specs",
    )
    # 哪个 SDD 仓（非空，幂等键之一）；related_name="+" 不污染 Repository 反查。
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="+",
    )
    # SPEC-02 追溯；可空对齐 chat 自然语言需求（INV-2）。
    work_item = models.ForeignKey(
        "delivery.WorkItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sdd_specs",
    )
    # SPEC-02 来源方案版本；SET_NULL 删版本不抹脊柱。
    plan_version = models.ForeignKey(
        "delivery.PlanVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sdd_specs",
    )
    status = models.CharField(
        max_length=16,
        choices=SddSpecStatus.choices,
        default=SddSpecStatus.DRAFT,
    )
    change_kind = models.CharField(
        max_length=16,
        choices=SddSpecChangeKind.choices,
        default=SddSpecChangeKind.PROPOSAL,
    )
    # spec→实现 PR 关联（Phase 52 D-52-1，LINK-01）：编码产出的 PR 回填于此，元素形如
    # ``{pr_url, repository_id, linked_at}``（linked_at 为 ISO8601 字符串）。spec→WorkItem
    # 关联已由 work_item FK 承载，本字段只补 spec→PR。写入只经 SddSpecService
    # .link_implementation_pr（INV-6）；default=list 既有行天然降级为空列表（nullable 无回填）。
    implementation_prs = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_sdd_spec"
        verbose_name = "SDD 规格"
        verbose_name_plural = "SDD 规格"
        # 幂等键：同一方案版本对同一仓只产一份 spec（D-49-1）。
        unique_together = (("plan_version", "repository"),)
        indexes = [
            models.Index(fields=["repository"]),
            models.Index(fields=["work_item"]),
        ]

    def __str__(self) -> str:
        return f"SddSpec({self.id}, {self.status})"
