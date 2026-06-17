"""delivery URL configuration（Phase 28-03 最小 REST）。

字面段路由（IsAuthenticated）：手动 upsert + 按三元组读取 WorkItem。
"""

from django.urls import path

from delivery.api.views import (
    IngestBatchDetailView,
    IngestBatchDispatchView,
    IngestDispatchView,
    IngestRunDetailView,
    ReleaseBitablePreviewView,
    ReleaseBitableSyncView,
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
    # 批量摄取触发 + 状态回流（字面段 batch/ 必须在 <uuid:run_id> 之前注册）
    path(
        "ingest/batch/",
        IngestBatchDispatchView.as_view(),
        name="ingest-batch-dispatch",
    ),
    path(
        "ingest/batch/<uuid:batch_id>/",
        IngestBatchDetailView.as_view(),
        name="ingest-batch-detail",
    ),
    # 单组摄取触发 + 状态回流（字面段在前；状态端点含 uuid run_id）
    path("ingest/", IngestDispatchView.as_view(), name="ingest-dispatch"),
    path(
        "ingest/<uuid:run_id>/",
        IngestRunDetailView.as_view(),
        name="ingest-run-detail",
    ),
    # 上线文档（Bitable）同步：预览（只读） + 批量入库
    path(
        "release/bitable/preview/",
        ReleaseBitablePreviewView.as_view(),
        name="release-bitable-preview",
    ),
    path(
        "release/bitable/sync/",
        ReleaseBitableSyncView.as_view(),
        name="release-bitable-sync",
    ),
    # 截图识别需求（字面段，multipart 上传 + IsAuthenticated）
    path(
        "screenshot-recall/",
        ScreenshotRecallView.as_view(),
        name="screenshot-recall",
    ),
]
