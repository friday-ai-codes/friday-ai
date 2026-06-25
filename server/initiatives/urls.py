"""initiatives URL configuration（/api/projects/）。"""

from django.urls import path

from initiatives.views import (
    ArtifactDetailView,
    ArtifactListCreateView,
    ArtifactViewView,
    ProjectDetailView,
    ProjectGraphView,
    ProjectKnowledgeLinkView,
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
    # 工件（ARTIFACT-02/03）
    path(
        "<uuid:project_id>/artifacts/",
        ArtifactListCreateView.as_view(),
        name="project-artifact-list",
    ),
    path(
        "<uuid:project_id>/artifacts/<uuid:artifact_id>/",
        ArtifactDetailView.as_view(),
        name="project-artifact-detail",
    ),
    path(
        "<uuid:project_id>/artifacts/<uuid:artifact_id>/view/",
        ArtifactViewView.as_view(),
        name="project-artifact-view",
    ),
    # 知识关联（KLINK-01/02）
    path(
        "<uuid:project_id>/knowledge/",
        ProjectKnowledgeLinkView.as_view(),
        name="project-knowledge-link",
    ),
    path(
        "<uuid:project_id>/graph/",
        ProjectGraphView.as_view(),
        name="project-graph",
    ),
]
