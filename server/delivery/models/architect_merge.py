"""架构师融合产出模型（DOMAIN §6，Phase 40-01）。

立 v0.7 方案编排「reduce 段」的落库底座：

- **``ArchitectMerge``**：记录每次架构师融合（reduce）的验证结果。``session`` 归属一次
  ``PlanSession`` 编排（删 session 级联删融合记录，CASCADE）；``merged_plan_version``
  **软引用** ``PlanVersion.id``（``UUIDField(null=True)``，与 ``PlanSession.current_plan_version``
  / Phase 36/37 软引用范式一致，不建硬 FK 避免 delivery 内循环——passed 时由 40-02 写入，
  failed 时留 null）；``validation_status`` **默认 failed**（fail-closed：未明确通过即视为
  失败，对齐 MERGE-02 拦截语义）；``validation_report`` 落 PlanValidator 报告；``attempt``
  承载 40-02 限次回退计数。

设计要点（守 INV-6 精神）：状态/落库**只经 40-02 融合 service/adapter**，本模型层
**不写**任何 create/save/状态变更业务方法；旁路写表由 INV-6 grep 守护断言。跨 app FK
用字符串前向引用避免 import 环（对齐 ``RepoResearchTask`` 用 "delivery.PlanSession"
字符串引用范式）。
"""

import uuid

from django.db import models


class ArchitectMergeStatus(models.TextChoices):
    """架构师融合验证状态枚举（passed|failed，对齐 DOMAIN §6）。"""

    PASSED = "passed", "通过"
    FAILED = "failed", "失败"


class ArchitectMerge(models.Model):
    """架构师融合产出（每次 reduce 段融合的验证结果，DOMAIN §6）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 ConvergenceSession 收敛；删 session 级联删其融合记录
    session = models.ForeignKey(
        "delivery.ConvergenceSession",
        on_delete=models.CASCADE,
        related_name="architect_merges",
    )
    # 软引用 ArtifactVersion.id（不建硬 FK 避免 delivery 内循环）；passed 时写入，
    # failed 时留 null（不落产物）。
    merged_artifact_version = models.UUIDField(null=True, blank=True)
    # fail-closed：未明确通过即视为失败（对齐 MERGE-02 拦截语义）
    validation_status = models.CharField(
        max_length=16,
        choices=ArchitectMergeStatus.choices,
        default=ArchitectMergeStatus.FAILED,
    )
    # PlanValidator 结构化报告（{valid, errors, warnings} 或降级 reason）
    validation_report = models.JSONField(default=dict, blank=True)
    # 40-02 限次回退计数（本次融合序号）
    attempt = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_architect_merge"
        verbose_name = "架构师融合"
        verbose_name_plural = "架构师融合"
        indexes = [
            models.Index(fields=["session", "validation_status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ArchitectMerge({self.id}, {self.validation_status})"
