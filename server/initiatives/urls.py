"""initiatives URL configuration（/api/projects/）。"""

from django.urls import path

from initiatives.views import (
    ProjectDetailView,
    ProjectListCreateView,
    ProjectMemberDetailView,
    ProjectMemberListView,
    ProjectOwnerTransferView,
    ProjectTransitionView,
)

urlpatterns = [
    path("", ProjectListCreateView.as_view(), name="project-list"),
    path("<uuid:project_id>/", ProjectDetailView.as_view(), name="project-detail"),
    path(
        "<uuid:project_id>/transition/",
        ProjectTransitionView.as_view(),
        name="project-transition",
    ),
    path(
        "<uuid:project_id>/transfer-owner/",
        ProjectOwnerTransferView.as_view(),
        name="project-transfer-owner",
    ),
    path(
        "<uuid:project_id>/members/",
        ProjectMemberListView.as_view(),
        name="project-member-list",
    ),
    path(
        "<uuid:project_id>/members/<uuid:user_id>/",
        ProjectMemberDetailView.as_view(),
        name="project-member-detail",
    ),
]
