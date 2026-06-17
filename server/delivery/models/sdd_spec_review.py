"""SddSpecReview append-only 评审记录（delivery app，Phase 50-02 SPECST-02）。

为 ``SddSpec`` 评审建立**不可篡改**的审计底座——每条评审即一次审批留痕：

- **``SddSpecReview``**：``spec`` FK（CASCADE：删 spec 连带清其评审历史）、``reviewer``
  FK（→ ``settings.AUTH_USER_MODEL``，SET_NULL：删用户不灭评审，仅置空归属，保留留痕）、
  ``decision``（approve/reject）、``comment``（评审意见，可空）、``created_at``（落库即时刻）。

设计契约（守 INV-6 + 不可篡改）：
- **append-only**：模型层**不**定义任何 edit/delete/update/apply 业务写方法（仅 ``__str__``）。
  评审记录唯一写入点是 ``SddSpecService.approve`` / ``reject``（plan 50-02，单一事务内建评审 +
  驱动状态）；旁路写表由 ``test_sdd_spec_inv6_guard`` grep 守护断言。
- 跨 app FK（``AUTH_USER_MODEL``）与同 app FK（``delivery.SddSpec``）均用字符串前向引用，
  避免 import 环（对齐 ``sdd_spec.py`` 字符串 FK 范式）。
"""

import uuid

from django.conf import settings
from django.db import models


class ReviewDecision(models.TextChoices):
    """评审结论枚举：批准 / 驳回（驱动 SddSpec 状态流转，plan 50-02）。"""

    APPROVE = "approve", "批准"
    REJECT = "reject", "驳回"


class SddSpecReview(models.Model):
    """SddSpec 不可篡改评审记录（append-only，SPECST-02）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 被评审的 spec；CASCADE：删 spec 连带清其评审历史。
    spec = models.ForeignKey(
        "delivery.SddSpec",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    # 评审人；SET_NULL + null：删用户不灭评审记录，仅置空归属（保留审计留痕）。
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    decision = models.CharField(
        max_length=16,
        choices=ReviewDecision.choices,
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_sdd_spec_review"
        verbose_name = "SDD 规格评审"
        verbose_name_plural = "SDD 规格评审"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["spec", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"SddSpecReview({self.id}, {self.decision})"
