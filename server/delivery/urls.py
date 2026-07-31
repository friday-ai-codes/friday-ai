"""delivery URL configuration（Phase 28-03 最小 REST）。

字面段路由（IsAuthenticated）：手动 upsert + 按三元组读取 WorkItem。
"""

from django.urls import path

from delivery.api.artifact_views import (
    ArtifactListView,
    ArtifactTimelineView,
    ArtifactVersionDownstreamView,
)
from delivery.api.blueprint_doc_views import (
    BlueprintDocumentView,
    BlueprintEventsView,
    BlueprintReviewThreadsView,
)
from delivery.api.blueprint_gate_views import (
    BlueprintGateAddRepoView,
    BlueprintGateConfirmView,
    BlueprintGateEditResponsibilityView,
    BlueprintGateReclassifyRoleView,
    BlueprintGateRemoveRepoView,
    BlueprintGateSnapshotView,
    BlueprintGateUpgradeResearchView,
    BlueprintRejectedToBoundaryView,
)
from delivery.api.blueprint_list_views import BlueprintListView
from delivery.api.blueprint_review_views import (
    BlueprintReviewApproveView,
    BlueprintReviewEditBlocksView,
    BlueprintReviewFindingDismissView,
    BlueprintReviewFindingResolveView,
    BlueprintReviewRejectView,
    BlueprintReviewSnapshotView,
    BlueprintReviewThreadAnswerView,
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
    # 115-01 蓝图列表（VIEW-03/VIEW-04）：**顶层字面段**，不在 artifacts/ 分组内。可见性口径
    # 与 artifact 级端点不同（先算成员项目集合再过滤，见 blueprint_list_views 模块 docstring）。
    path("blueprints/", BlueprintListView.as_view(), name="blueprint-list"),
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
    # 阶段 1 出口确认门（112-05，FLOW-03/FLOW-04）：1 个只读快照 + 7 个动作端点。
    # 全部挂在 artifacts/<uuid>/blueprint-gate/ 下（字面动作段，与 artifact-timeline
    # 的整段精确匹配互不遮挡）。
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/",
        BlueprintGateSnapshotView.as_view(),
        name="blueprint-gate-snapshot",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/confirm/",
        BlueprintGateConfirmView.as_view(),
        name="blueprint-gate-confirm",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/remove-repo/",
        BlueprintGateRemoveRepoView.as_view(),
        name="blueprint-gate-remove-repo",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/add-repo/",
        BlueprintGateAddRepoView.as_view(),
        name="blueprint-gate-add-repo",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/reclassify-role/",
        BlueprintGateReclassifyRoleView.as_view(),
        name="blueprint-gate-reclassify-role",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/edit-responsibility/",
        BlueprintGateEditResponsibilityView.as_view(),
        name="blueprint-gate-edit-responsibility",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/rejected-to-boundary/",
        BlueprintRejectedToBoundaryView.as_view(),
        name="blueprint-gate-rejected-to-boundary",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-gate/upgrade-research/",
        BlueprintGateUpgradeResearchView.as_view(),
        name="blueprint-gate-upgrade-research",
    ),
    # 阶段 4 人审（114-05，FLOW-07 / CLAR-03 / CLAR-04）：1 个只读快照 + 6 个动作端点
    # （含 B2 的 finding 处置两端点），前缀 blueprint-review/ 与阶段 1 的 blueprint-gate/
    # 区分。字面段 threads/ 在 <uuid:thread_id> 之前；三个 threads/<uuid>/<动作>/ 路由的
    # 动作段互不重叠，与 artifact-timeline 的整段精确匹配同样互不遮挡。
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/",
        BlueprintReviewSnapshotView.as_view(),
        name="blueprint-review-snapshot",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/approve/",
        BlueprintReviewApproveView.as_view(),
        name="blueprint-review-approve",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/reject/",
        BlueprintReviewRejectView.as_view(),
        name="blueprint-review-reject",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/edit-blocks/",
        BlueprintReviewEditBlocksView.as_view(),
        name="blueprint-review-edit-blocks",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/threads/<uuid:thread_id>/answer/",
        BlueprintReviewThreadAnswerView.as_view(),
        name="blueprint-review-thread-answer",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/threads/<uuid:thread_id>/resolve/",
        BlueprintReviewFindingResolveView.as_view(),
        name="blueprint-review-thread-resolve",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/threads/<uuid:thread_id>/dismiss/",
        BlueprintReviewFindingDismissView.as_view(),
        name="blueprint-review-thread-dismiss",
    ),
    # 115-01 蓝图只读供数面（VIEW-01 / CLAR-01）：正文（含 quality）/ 阶段事件 / 线程详情
    # 集合（GET 读多轮 + POST 开选区评论，同一集合资源的两个 HTTP 方法，不是 ?action= 分派）。
    # blueprint/ 与 blueprint/events/ 是两个整段精确匹配，互不遮挡；blueprint-review/threads/
    # 的字面段 threads/ 与既有 threads/<uuid:thread_id>/<动作>/ 整段不同，按既有纪律**字面段
    # 写在前面**（保持读者预期一致）。
    path(
        "artifacts/<uuid:artifact_id>/blueprint/",
        BlueprintDocumentView.as_view(),
        name="blueprint-document",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint/events/",
        BlueprintEventsView.as_view(),
        name="blueprint-events",
    ),
    path(
        "artifacts/<uuid:artifact_id>/blueprint-review/threads/",
        BlueprintReviewThreadsView.as_view(),
        name="blueprint-review-threads",
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
