"""Clarification：HITL 澄清问答模型（DOMAIN §6/§12/§14，CLARIFY-01）。

编排在不清晰时发 ``Clarification`` 挂起等用户，回答后仅 ``affected_partials`` 内的
``RepoResearchTask`` 重跑、其余 partial 复用（§14 clarifying 挂起/重跑规则）。

设计要点（守 INV-6 精神）：
- **写入单一入口**：落库/状态变更只经 ``ClarificationService``，模型层**不写**任何
  create/save/answer 业务方法（旁路写表由 INV-6 grep 守护断言）。
- **pending 语义**：clarification pending = 存在 ``answered_at IS NULL`` 的 Clarification
  （由 service/engine 判定，不在模型上加方法）。
- **affected_partials**：M2M 指向回答后须重跑的 ``RepoResearchTask``；``related_name="+"``
  不污染 RepoResearchTask 反查。
"""

import uuid

from django.db import models


class Clarification(models.Model):
    """HITL 澄清问答（§6 字段 + affected_partials 重跑面）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 PlanSession 编排；删 session 级联删其澄清
    session = models.ForeignKey(
        "delivery.PlanSession",
        on_delete=models.CASCADE,
        related_name="clarifications",
    )
    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    # 回答后哪些 task 须重跑；related_name="+" 不污染 RepoResearchTask 反查
    affected_partials = models.ManyToManyField(
        "delivery.RepoResearchTask",
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_clarification"
        verbose_name = "澄清问答"
        verbose_name_plural = "澄清问答"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session"]),
        ]

    def __str__(self) -> str:
        pending = self.answered_at is None
        return f"Clarification({self.id}, pending={pending})"
