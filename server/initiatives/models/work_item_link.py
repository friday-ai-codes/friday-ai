"""ProjectWorkItemLink 组合关系边（COMPOSE-01/02）。

项目↔WorkItem 的轻量 through 关系表：story 与缺陷**统一复用 `delivery.WorkItem`**
（按 `work_item_type` 区分），缺陷不重复建模为工件（COMPOSE-02）。``provenance`` 区分
来源（board_derived 自动并入 / manual 手动并入）。

KnowledgeEdge 富建模留 Phase 79（KLINK）；本期与 Phase 77 项目↔项目关系一致取轻量关系表。
模型层无业务写方法（INV-6，attach/detach 收口于 ``ProjectService``）。
"""

from __future__ import annotations

import uuid

from django.db import models


class LinkProvenance(models.TextChoices):
    """组合关系来源。"""

    BOARD_DERIVED = "board_derived", "看板派生"
    MANUAL = "manual", "手动并入"


class ProjectWorkItemLink(models.Model):
    """项目↔WorkItem 组合关系（一项目一工作项一行）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="work_item_links",
        verbose_name="项目",
    )
    work_item = models.ForeignKey(
        "delivery.WorkItem",
        on_delete=models.CASCADE,
        related_name="project_links",
        verbose_name="工作项",
    )
    provenance = models.CharField(
        max_length=20,
        choices=LinkProvenance.choices,
        default=LinkProvenance.MANUAL,
        verbose_name="来源",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_work_item_links"
        verbose_name = "项目工作项关联"
        verbose_name_plural = "项目工作项关联"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "work_item"], name="uniq_project_work_item_link"
            ),
        ]
        indexes = [
            models.Index(fields=["project", "provenance"]),
            models.Index(fields=["work_item"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id} ↔ {self.work_item_id} ({self.provenance})"
