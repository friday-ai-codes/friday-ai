"""ProjectRelation 项目↔项目轻量关联（PROJ-04）。

自引用 M2M 的 through 模型（``symmetrical=False``），用于"历史迭代/相关项目"回看。
KnowledgeEdge 富建模留 Phase 79（KLINK-02）——本期最小可用关联表，不提前耦合知识图谱。
模型层无业务写方法（INV-6，收口于 ``ProjectService``）。
"""

from __future__ import annotations

import uuid

from django.db import models


class ProjectRelation(models.Model):
    """项目→项目有向关联（带备注）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="outgoing_relations",
        verbose_name="源项目",
    )
    target = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="incoming_relations",
        verbose_name="目标项目",
    )
    note = models.CharField(
        max_length=200, blank=True, default="", verbose_name="关联备注"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "initiative_project_relations"
        verbose_name = "项目关联"
        verbose_name_plural = "项目关联"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target"], name="uniq_project_relation_pair"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_id} -> {self.target_id}"
