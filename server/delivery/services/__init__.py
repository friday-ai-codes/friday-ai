"""delivery services 包 —— 操作态脊柱写入入口与派生纯函数。

re-export ``WorkItemService`` / ``WorkItemIdentity``（WorkItem 单一写入入口，INV-6）
+ ``CommentEventService`` / ``classify_approval_semantic``（评论事件单一写入入口，CMT-01）。
"""

from delivery.services.comment_event_service import (
    CommentEventService,
    classify_approval_semantic,
)
from delivery.services.work_item_service import WorkItemIdentity, WorkItemService

__all__ = [
    "WorkItemService",
    "WorkItemIdentity",
    "CommentEventService",
    "classify_approval_semantic",
]
