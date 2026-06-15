"""delivery services 包 —— 操作态脊柱写入入口与派生纯函数。

re-export ``WorkItemService`` / ``WorkItemIdentity``（单一写入入口，INV-6）。
"""

from delivery.services.work_item_service import WorkItemIdentity, WorkItemService

__all__ = ["WorkItemService", "WorkItemIdentity"]
