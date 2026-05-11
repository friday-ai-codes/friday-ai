"""Repositories URL configuration."""
from adrf.routers import DefaultRouter
from django.urls import include, path
from .index_views import (
 BranchIndexListView,
 CodeSearchView,
 EmbeddingHealthView,
 IndexDeleteView,
 IndexFreshnessView,
 IndexHistoryListView,
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
from .refresh_remote_head_views import RefreshRemoteHeadView
from .route_views import RepoRouteView
from .sync_status_views import SyncStatusView
from .views import CacheManagementView, RepositoryViewSet, SetAccessTokenView, TestConnectionView
router = DefaultRouter # trailing_slash=True by default
router.register("", RepositoryViewSet, basename="repository")
urlpatterns = [
 # Cache management (must be before router to avoid being matched as repository id)
 path(
 "cache/",
 CacheManagementView.as_view,
 name="cache-management",
 ),
 # Test connection (must be before router to avoid being matched as repository id)
 path(
 "test-connection/",
 TestConnectionView.as_view,
 name="test-connection",
 ),
 # Health checks (must be before router)
 path(
 "health/qdrant/",
 QdrantHealthView.as_view,
 name="qdrant-health",
 ),
 path(
 "health/embedding/",
 EmbeddingHealthView.as_view,
 name="embedding-health",
 ),
 path(
 "health/reranker/",
 RerankerHealthView.as_view,
 name="reranker-health",
 ),
 # Phase (per ): 仓库路由 API —— 必须在 router 之前以避免被匹配为 repository id
 path(
 "route/",
 RepoRouteView.as_view,
 name="repository-route",
 ),
 # Router URLs
 path("", include(router.urls)),
 # Repository-specific endpoints
 path(
 "<uuid:repository_id>/credential/access-token/",
 SetAccessTokenView.as_view,
 name="set-access-token",
 ),
 path(
 "<uuid:repository_id>/test-connection/",
 TestConnectionView.as_view,
 name="repository-test-connection",
 ),
 path(
 "<uuid:repository_id>/branch-indexes/",
 BranchIndexListView.as_view,
 name="repository-branch-indexes",
 ),
 # Index management
 path(
 "<uuid:repository_id>/index/",
 IndexTriggerView.as_view,
 name="repository-index-trigger",
 ),
 path(
 "<uuid:repository_id>/index/status/",
 IndexStatusView.as_view,
 name="repository-index-status",
 ),
 path(
 "<uuid:repository_id>/index/delete/",
 IndexDeleteView.as_view,
 name="repository-index-delete",
 ),
 # Code search
 path(
 "<uuid:repository_id>/search/",
 CodeSearchView.as_view,
 name="repository-code-search",
 ),
 # Index observability (Phase)
 path(
 "<uuid:repository_id>/index/history/",
 IndexHistoryListView.as_view,
 name="repository-index-history",
 ),
 path(
 "<uuid:repository_id>/index/stats/",
 IndexStatsView.as_view,
 name="repository-index-stats",
 ),
 path(
 "<uuid:repository_id>/index/health/",
 RepositoryCollectionHealthView.as_view,
 name="repository-index-health",
 ),
 path(
 "<uuid:repository_id>/index/freshness/",
 IndexFreshnessView.as_view,
 name="repository-index-freshness",
 ),
 # Snapshot export/import
 path(
 "<uuid:repository_id>/index/snapshot/export/",
 IndexSnapshotExportView.as_view,
 name="repository-index-snapshot-export",
 ),
 path(
 "<uuid:repository_id>/index/snapshot/import/",
 IndexSnapshotImportView.as_view,
 name="repository-index-snapshot-import",
 ),
 # Webhook (Phase, no auth required)
 path(
 "<uuid:repository_id>/webhooks/push/",
 RepositoryWebhookView.as_view,
 name="repository-webhook-push",
 ),
 # 同步状态查询（Phase / ）
 path(
 "<uuid:repository_id>/sync-status/",
 SyncStatusView.as_view,
 name="repository-sync-status",
 ),
 # Hash 新鲜度立即刷新（Phase）
 path(
 "<uuid:repository_id>/refresh-remote-head/",
 RefreshRemoteHeadView.as_view,
 name="repository-refresh-remote-head",
 ),
 # codegraph API（Phase）：必须在末尾，UUID 通配符顺序安全
 path("<uuid:repository_id>/codegraph/", include("codegraph.urls")),
]
