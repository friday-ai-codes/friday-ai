"""Repositories URL configuration."""

from adrf.routers import DefaultRouter
from django.urls import include, path

from .index_views import (
    BranchIndexListView,
    CodeSearchView,
    EmbeddingHealthView,
    GraphRagStatusView,
    IndexCancelView,
    IndexDeleteView,
    IndexedFilesListView,
    IndexFreshnessView,
    IndexHistoryListView,
    IndexProgressStreamView,
    IndexSnapshotExportView,
    IndexSnapshotImportView,
    IndexStatsView,
    IndexStatusView,
    IndexTriggerView,
    QdrantHealthView,
    RepositoryCollectionHealthView,
    RepositoryWebhookView,
    RerankerHealthView,
)
from .graph_search_views import GraphSearchView
from .refresh_remote_head_views import RefreshRemoteHeadView
from .route_views import RepoRouteView
from .sync_status_views import SyncStatusView
from .tree_views import (
    KnowledgeTreeFacetView,
    KnowledgeTreePinView,
    KnowledgeTreeRebuildView,
    KnowledgeTreeSearchView,
    KnowledgeTreeView,
    RepositoryIndexTreeView,
)
from .views import CacheManagementView, RepositoryViewSet, SetAccessTokenView, TestConnectionView

router = DefaultRouter()  # trailing_slash=True by default
router.register("", RepositoryViewSet, basename="repository")

urlpatterns = [
    # Cache management (must be before router to avoid being matched as repository id)
    path(
        "cache/",
        CacheManagementView.as_view(),
        name="cache-management",
    ),
    # Test connection (must be before router to avoid being matched as repository id)
    path(
        "test-connection/",
        TestConnectionView.as_view(),
        name="test-connection",
    ),
    # Health checks (must be before router)
    path(
        "health/qdrant/",
        QdrantHealthView.as_view(),
        name="qdrant-health",
    ),
    path(
        "health/embedding/",
        EmbeddingHealthView.as_view(),
        name="embedding-health",
    ),
    path(
        "health/reranker/",
        RerankerHealthView.as_view(),
        name="reranker-health",
    ),
    # implementation (per contract): 仓库路由 API —— 必须在 router 之前以避免被匹配为 repository id
    path(
        "route/",
        RepoRouteView.as_view(),
        name="repository-route",
    ),
    # PageIndex 知识树浏览（必须在 router 之前）
    path(
        "knowledge-tree/",
        KnowledgeTreeView.as_view(),
        name="knowledge-tree",
    ),
    path(
        "knowledge-tree/facet/",
        KnowledgeTreeFacetView.as_view(),
        name="knowledge-tree-facet",
    ),
    path(
        "knowledge-tree/search/",
        KnowledgeTreeSearchView.as_view(),
        name="knowledge-tree-search",
    ),
    path(
        "knowledge-tree/rebuild/",
        KnowledgeTreeRebuildView.as_view(),
        name="knowledge-tree-rebuild",
    ),
    path(
        "knowledge-tree/pin/",
        KnowledgeTreePinView.as_view(),
        name="knowledge-tree-pin",
    ),
    # Router URLs
    path("", include(router.urls)),
    # Repository-specific endpoints
    path(
        "<uuid:repository_id>/credential/access-token/",
        SetAccessTokenView.as_view(),
        name="set-access-token",
    ),
    path(
        "<uuid:repository_id>/test-connection/",
        TestConnectionView.as_view(),
        name="repository-test-connection",
    ),
    path(
        "<uuid:repository_id>/branch-indexes/",
        BranchIndexListView.as_view(),
        name="repository-branch-indexes",
    ),
    # Index management
    path(
        "<uuid:repository_id>/index/",
        IndexTriggerView.as_view(),
        name="repository-index-trigger",
    ),
    path(
        "<uuid:repository_id>/index/status/",
        IndexStatusView.as_view(),
        name="repository-index-status",
    ),
    path(
        "<uuid:repository_id>/index/graphrag-status/",
        GraphRagStatusView.as_view(),
        name="repository-graphrag-status",
    ),
    path(
        "<uuid:repository_id>/index/cancel/",
        IndexCancelView.as_view(),
        name="repository-index-cancel",
    ),
    path(
        "<uuid:repository_id>/index/delete/",
        IndexDeleteView.as_view(),
        name="repository-index-delete",
    ),
    # PageIndex 单仓能力树
    path(
        "<uuid:repository_id>/index-tree/",
        RepositoryIndexTreeView.as_view(),
        name="repository-index-tree",
    ),
    # Code search
    path(
        "<uuid:repository_id>/search/",
        CodeSearchView.as_view(),
        name="repository-code-search",
    ),
    # GraphRAG 关联搜索（implementation）：放在 codegraph include 之前，
    # graph-search/ 与 codegraph/ 字面不冲突，UUID 通配符顺序安全。
    path(
        "<uuid:repository_id>/graph-search/",
        GraphSearchView.as_view(),
        name="repository-graph-search",
    ),
    # Index observability (implementation)
    path(
        "<uuid:repository_id>/index/history/",
        IndexHistoryListView.as_view(),
        name="repository-index-history",
    ),
    # contract：已索引文件清单查询（搜索 + 分页）
    path(
        "<uuid:repository_id>/indexed-files/",
        IndexedFilesListView.as_view(),
        name="repository-indexed-files",
    ),
    # SSE 实时进度流（contract — 让"索引历史"列表 RUNNING 行可显示实时进度）
    path(
        "<uuid:repository_id>/index/stream/",
        IndexProgressStreamView.as_view(),
        name="repository-index-stream",
    ),
    path(
        "<uuid:repository_id>/index/stats/",
        IndexStatsView.as_view(),
        name="repository-index-stats",
    ),
    path(
        "<uuid:repository_id>/index/health/",
        RepositoryCollectionHealthView.as_view(),
        name="repository-index-health",
    ),
    path(
        "<uuid:repository_id>/index/freshness/",
        IndexFreshnessView.as_view(),
        name="repository-index-freshness",
    ),
    # Snapshot export/import
    path(
        "<uuid:repository_id>/index/snapshot/export/",
        IndexSnapshotExportView.as_view(),
        name="repository-index-snapshot-export",
    ),
    path(
        "<uuid:repository_id>/index/snapshot/import/",
        IndexSnapshotImportView.as_view(),
        name="repository-index-snapshot-import",
    ),
    # Webhook (implementation, no auth required)
    path(
        "<uuid:repository_id>/webhooks/push/",
        RepositoryWebhookView.as_view(),
        name="repository-webhook-push",
    ),
    # 同步状态查询（implementation contract / contract）
    path(
        "<uuid:repository_id>/sync-status/",
        SyncStatusView.as_view(),
        name="repository-sync-status",
    ),
    # Hash 新鲜度立即刷新（implementation contract）
    path(
        "<uuid:repository_id>/refresh-remote-head/",
        RefreshRemoteHeadView.as_view(),
        name="repository-refresh-remote-head",
    ),
    # codegraph API（implementation contract）：必须在末尾，UUID 通配符顺序安全
    path("<uuid:repository_id>/codegraph/", include("codegraph.urls")),
]
