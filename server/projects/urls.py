"""Spaces URL configuration."""

from adrf.routers import DefaultRouter
from django.urls import include, path

from .members_views import SpaceMemberDetailView, SpaceMemberListView
from .views import (
    SpaceRepositoryDetailView,
    SpaceRepositoryListCreateView,
    SpaceViewSet,
)

router = DefaultRouter()  # trailing_slash=True by default
router.register("", SpaceViewSet, basename="space")

urlpatterns = [
    # 空间仓库关联管理（新 API，需在 router 之前注册以优先匹配）
    path(
        "<str:space_id>/repositories/",
        SpaceRepositoryListCreateView.as_view(),
        name="space-repository-list",
    ),
    path(
        "<str:space_id>/repositories/<str:pk>/",
        SpaceRepositoryDetailView.as_view(),
        name="space-repository-detail",
    ),
    # 空间成员管理
    path("<str:space_id>/members/", SpaceMemberListView.as_view(), name="space-member-list"),
    path("<str:space_id>/members/<str:user_id>/", SpaceMemberDetailView.as_view(), name="space-member-detail"),
    path("", include(router.urls)),
]
