"""Projects URL configuration."""
from django.urls import include, path
from adrf.routers import DefaultRouter
from .views import ProjectViewSet
from .members_views import ProjectMemberDetailView, ProjectMemberListView
router = DefaultRouter # trailing_slash=True by default
router.register("", ProjectViewSet, basename="project")
urlpatterns = [
 path("", include(router.urls)),
 # 项目成员管理
 path("<str:project_id>/members/", ProjectMemberListView.as_view, name="project-member-list"),
 path("<str:project_id>/members/<str:user_id>/", ProjectMemberDetailView.as_view, name="project-member-detail"),
]
