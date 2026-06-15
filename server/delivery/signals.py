"""delivery 信号 —— WorkItem 同步完成事件（best-effort）。

``work_item_synced`` 在 ``WorkItemService.upsert`` 末尾 best-effort 发出（订阅者
异常被吞掉 + warning，不影响落库）。下游（knowledge 投影 / 通知）按需订阅。

payload 约定：``{work_item_id: str, facets: list[str]}``。
"""

from django.dispatch import Signal

__all__ = ["work_item_synced"]

work_item_synced = Signal()
