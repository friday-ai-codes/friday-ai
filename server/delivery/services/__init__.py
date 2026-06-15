"""delivery services 包 —— 操作态脊柱写入入口与派生纯函数。

re-export ``WorkItemService`` / ``WorkItemIdentity``（WorkItem 单一写入入口，INV-6）
+ ``CommentEventService`` / ``classify_approval_semantic``（评论事件单一写入入口，CMT-01）
+ ``DocumentService`` / ``derive_feishu_tenant``（Document 单一写入入口，DOC-01/INV-6）
+ ``ReleaseService``（Release 账本单一写入入口，REL-01/INV-6）
+ ``BitableReleaseAdapter``（Bitable 行 → ReleaseService 落库骨架，REL-02）。
"""

from delivery.services.bitable_release_adapter import BitableReleaseAdapter
from delivery.services.comment_event_service import (
    CommentEventService,
    classify_approval_semantic,
)
from delivery.services.comment_projection import (
    aproject_comment_tree,
    project_comment_tree,
)
from delivery.services.document_service import DocumentService, derive_feishu_tenant
from delivery.services.release_service import ReleaseService
from delivery.services.work_item_service import WorkItemIdentity, WorkItemService

__all__ = [
    "WorkItemService",
    "WorkItemIdentity",
    "CommentEventService",
    "classify_approval_semantic",
    "project_comment_tree",
    "aproject_comment_tree",
    "DocumentService",
    "derive_feishu_tenant",
    "ReleaseService",
    "BitableReleaseAdapter",
]
