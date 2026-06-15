"""WorkItemRelation：从飞书关联型字段派生的工作项关系（DOMAIN §12.3，WIT-04）。

实测关系主要来自 ``work_item_related_multi_select`` 字段（独立 relation 端点疑似
失效，PF-10）。目标工作项尚未 upsert 时用 ``target_external_id`` 占位，待目标
落库后回填 ``target_work_item``。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class RelationType(models.TextChoices):
    """关系类型枚举。"""

    BELONGS_TO_PROJECT = "belongs_to_project", "所属项目"
    SPRINT = "sprint", "所属迭代"
    VERSION = "version", "规划/上车版本"
    RELATED = "related", "关联"


class RelationOrigin(models.TextChoices):
    """关系派生来源枚举。"""

    FEISHU_FIELD = "feishu_field", "飞书关联字段"
    FEISHU_RELATION_API = "feishu_relation_api", "飞书关系端点"
    FRIDAY = "friday", "Friday 本地"


class WorkItemRelation(models.Model):
    """工作项间派生关系（含目标未落库占位）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="out_relations",
    )
    target_work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="in_relations",
    )
    target_external_id = models.BigIntegerField(null=True, blank=True)
    relation_type = models.CharField(max_length=32, choices=RelationType.choices)
    source_field_key = models.CharField(max_length=64)
    origin = models.CharField(
        max_length=32,
        choices=RelationOrigin.choices,
        default=RelationOrigin.FEISHU_FIELD,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_work_item_relation"
        verbose_name = "工作项关系"
        verbose_name_plural = "工作项关系"
        unique_together = (
            (
                "source_work_item",
                "relation_type",
                "target_external_id",
                "source_field_key",
            ),
        )

    def __str__(self) -> str:
        return f"{self.source_work_item_id}-{self.relation_type}->{self.target_external_id}"
