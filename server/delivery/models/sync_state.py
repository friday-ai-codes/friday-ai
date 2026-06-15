"""WorkItemSyncState：按 facet 记录来源完整度（DOMAIN §12.2，WIT-03）。

upsert 不假装每次都拿到完整飞书真相——每个 facet 单独记 ``status`` 与
``last_synced_at``，部分 facet 失败不回滚整体 WorkItem。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem, WorkItemOrigin


class SyncFacet(models.TextChoices):
    """同步面（facet）枚举。"""

    BASIC_FIELDS = "basic_fields", "基础字段"
    PRD_BODY = "prd_body", "PRD 正文"
    TECH_DOC = "tech_doc", "技术方案正文"
    COMMENTS = "comments", "评论"
    RELATIONS = "relations", "关联关系"


class SyncStatus(models.TextChoices):
    """单 facet 完整度状态。"""

    COMPLETE = "complete", "完整"
    PARTIAL = "partial", "部分"
    MISSING = "missing", "缺失"
    STALE = "stale", "过期"


class WorkItemSyncState(models.Model):
    """某 WorkItem 某 facet 的来源完整度记录。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="sync_states",
    )
    facet = models.CharField(max_length=32, choices=SyncFacet.choices)
    status = models.CharField(max_length=16, choices=SyncStatus.choices)
    source = models.CharField(max_length=32, choices=WorkItemOrigin.choices)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_work_item_sync_state"
        verbose_name = "工作项同步状态"
        verbose_name_plural = "工作项同步状态"
        unique_together = (("work_item", "facet"),)

    def __str__(self) -> str:
        return f"{self.work_item_id}:{self.facet}={self.status}"
