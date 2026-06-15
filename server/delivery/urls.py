"""delivery URL configuration（Phase 28-03 最小 REST）。

字面段路由（IsAuthenticated）：手动 upsert + 按三元组读取 WorkItem。
"""

from django.urls import path

from delivery.api.views import (
    IngestDispatchView,
    IngestRunDetailView,
    ScreenshotRecallView,
    WorkItemCommentTreeView,
    WorkItemDetailView,
    WorkItemPrdDocumentView,
    WorkItemUpsertView,
)

urlpatterns = [
    path("work-items/upsert/", WorkItemUpsertView.as_view(), name="work-item-upsert"),
    path(
        "work-items/comments/",
        WorkItemCommentTreeView.as_view(),
        name="work-item-comment-tree",
    ),
    path(
        "work-items/prd-document/",
        WorkItemPrdDocumentView.as_view(),
        name="work-item-prd-document",
    ),
    path("work-items/", WorkItemDetailView.as_view(), name="work-item-detail"),
    # 一键摄取触发 + 状态回流（字面段在前；状态端点含 uuid run_id）
    path("ingest/", IngestDispatchView.as_view(), name="ingest-dispatch"),
    path(
        "ingest/<uuid:run_id>/",
        IngestRunDetailView.as_view(),
        name="ingest-run-detail",
    ),
    # 截图识别需求（字面段，multipart 上传 + IsAuthenticated）
    path(
        "screenshot-recall/",
        ScreenshotRecallView.as_view(),
        name="screenshot-recall",
    ),
]
