"""Repositories URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .index_views import (
 CodeSearchView,
 EmbeddingHealthView,
 IndexDeleteView,
 IndexStatusView,
 IndexTriggerView,
 QdrantHealthView,
 RerankerHealthView,
)
from .views import RepositoryViewSet, SetAccessTokenView
router = DefaultRouter # trailing_slash=True by default
router.register("", RepositoryViewSet, basename="repository")
urlpatterns = [
 path("", include(router.urls)),
 path(
 "<uuid:repository_id>/credential/access-token",
 SetAccessTokenView.as_view,
 name="set-access-token",
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
 # Health checks
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
]
