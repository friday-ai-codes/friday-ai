"""Repositories URL configuration."""
from django.urls import include, path
from adrf.routers import DefaultRouter
from .index_views import (
 CodeSearchView,
 EmbeddingHealthView,
 IndexDeleteView,
 IndexFreshnessView,
 IndexHistoryListView,
 IndexStatsView,
 IndexStatusView,
 IndexTriggerView,
 QdrantHealthView,
 RepositoryCollectionHealthView,
 RepositoryWebhookView,
)
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
 # Router URLs
 path("", include(router.urls)),
 # Repository-specific endpoints
 path(
 "<uuid:repository_id>/credential/access-token",
 SetAccessTokenView.as_view,
 name="set-access-token",
 ),
 path(
 "<uuid:repository_id>/test-connection/",
 TestConnectionView.as_view,
 name="repository-test-connection",
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
 # Webhook (Phase, no auth required)
 path(
 "<uuid:repository_id>/webhooks/push/",
 RepositoryWebhookView.as_view,
 name="repository-webhook-push",
 ),
]
