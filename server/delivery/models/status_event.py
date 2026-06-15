"""WorkItemStatusEvent：append-only 状态变更事件流（DOMAIN §12.4，WIT-05）。

状态变更记事件（pre/cur），非就地覆盖历史。来源：飞书 WorkitemStatusEvent
webhook + work item 响应内 ``work_item_status.history[]`` 回填。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class WorkItemStatusEvent(models.Model):
    """工作项状态变更事件（追加流）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    pre_state_key = models.CharField(max_length=64, blank=True, default="")
    cur_state_key = models.CharField(max_length=64, blank=True, default="")
    pre_sub_stage = models.CharField(max_length=64, blank=True, default="")
    cur_sub_stage = models.CharField(max_length=64, blank=True, default="")
    operator = models.CharField(max_length=128, blank=True, default="")
    event_time = models.DateTimeField(null=True, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_work_item_status_event"
        verbose_name = "工作项状态事件"
        verbose_name_plural = "工作项状态事件"
        indexes = [
            models.Index(fields=["work_item", "event_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.work_item_id}:{self.pre_state_key}->{self.cur_state_key}"
