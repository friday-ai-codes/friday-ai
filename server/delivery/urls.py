"""delivery URL configuration（Phase 28-03 最小 REST）。

字面段路由（IsAuthenticated）：手动 upsert + 按三元组读取 WorkItem。
"""

from django.urls import path

from delivery.api.artifact_views import (
    ArtifactListView,
    ArtifactTimelineView,
    ArtifactVersionDownstreamView,
)
from delivery.api.human_task_views import (
    ClarificationAnswerView,
    HumanTaskActionView,
    HumanTaskInboxView,
)
from delivery.api.views import (
    IngestBatchDetailView,
    IngestBatchDispatchView,
    IngestCrawlView,
    IngestDispatchView,
    IngestQueueActionView,
    IngestQueueDetailView,
    IngestQueueView,
    IngestRunDetailView,
    JsonIngestBatchView,
    JsonIngestResolveView,
    ScreenshotRecallView,
    WorkItemArtifactsView,
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
    path(
        "work-items/artifacts/",
        WorkItemArtifactsView.as_view(),
        name="work-item-artifacts",
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
    # URL 爬取：抓取飞书文档/多维表格/通用链接 → AI 抽成可关联条目（字面段）
    path(
        "ingest/crawl/",
        IngestCrawlView.as_view(),
        name="ingest-crawl",
    ),
    # JSON 批量摄取：解析预览 + 派发（字面段，须在 <uuid:run_id> 之前）
    path(
        "ingest/resolve/",
        JsonIngestResolveView.as_view(),
        name="ingest-json-resolve",
    ),
    # 爬取入库 durable 队列：入队/列表（GET=list/POST=enqueue）+ 单批明细 + 动作
    # （字面段 queue/ 在 <uuid:batch_id> 前；动作段 <str:action> 在 <uuid> 后）
    path(
        "ingest/queue/",
        IngestQueueView.as_view(),
        name="ingest-queue",
    ),
    path(
        "ingest/queue/<uuid:batch_id>/",
        IngestQueueDetailView.as_view(),
        name="ingest-queue-detail",
    ),
    path(
        "ingest/queue/<uuid:batch_id>/<str:action>/",
        IngestQueueActionView.as_view(),
        name="ingest-queue-action",
    ),
    path(
        "ingest/batch-json/",
        JsonIngestBatchView.as_view(),
        name="ingest-json-batch",
    ),
    # 单组摄取触发 + 状态回流（字面段在前；状态端点含 uuid run_id）
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
    # Artifact 版本轨 / 时间线（P7，只读呈现）：list（过滤）/ 版本时间线 / 下游引用聚合
    path("artifacts/", ArtifactListView.as_view(), name="artifact-list"),
    path(
        "artifacts/<uuid:artifact_id>/",
        ArtifactTimelineView.as_view(),
        name="artifact-timeline",
    ),
    path(
        "artifact-versions/<uuid:version_id>/downstream/",
        ArtifactVersionDownstreamView.as_view(),
        name="artifact-version-downstream",
    ),
    # Human Task Center（P8）：统一待办收件箱（list/open）+ 物化待办动作 + 投影澄清回流。
    # 字面段 clarification/ 必须在 <uuid:task_id> 动作路由之前注册（避免被 uuid 段吞）。
    path(
        "human-tasks/",
        HumanTaskInboxView.as_view(),
        name="human-task-inbox",
    ),
    path(
        "human-tasks/clarification/<uuid:clarification_id>/answer/",
        ClarificationAnswerView.as_view(),
        name="human-task-clarification-answer",
    ),
    path(
        "human-tasks/<uuid:task_id>/<str:action>/",
        HumanTaskActionView.as_view(),
        name="human-task-action",
    ),
]
