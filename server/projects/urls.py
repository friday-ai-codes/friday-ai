"""Projects URL configuration."""
from django.urls import include, path
from adrf.routers import DefaultRouter
from .views import (
 ProjectRepositoryDetailView,
 ProjectRepositoryListCreateView,
 ProjectViewSet,
)
from .members_views import ProjectMemberDetailView, ProjectMemberListView
router = DefaultRouter # trailing_slash=True by default
router.register("", ProjectViewSet, basename="project")
urlpatterns = [
 # 项目仓库关联管理（新 API，需在 router 之前注册以优先匹配）
 path(
 "<str:project_id>/repositories/",
 ProjectRepositoryListCreateView.as_view,
 name="project-repository-list",
 ),
 path(
 "<str:project_id>/repositories/<str:pk>/",
 ProjectRepositoryDetailView.as_view,
 name="project-repository-detail",
 ),
 # 项目成员管理
 path("<str:project_id>/members/", ProjectMemberListView.as_view, name="project-member-list"),
 path("<str:project_id>/members/<str:user_id>/", ProjectMemberDetailView.as_view, name="project-member-detail"),
 path("", include(router.urls)),
]
