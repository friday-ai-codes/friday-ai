"""initiatives URL configuration（/api/projects/）。"""

from django.urls import path

from initiatives.views import (
    ArtifactDetailView,
    ArtifactListCreateView,
    ArtifactViewView,
    ProjectCursorRulesView,
    ProjectDetailView,
    ProjectGraphView,
    ProjectKnowledgeLinkView,
    ProjectListCreateView,
    ProjectMemberDetailView,
    ProjectMemberListView,
    ProjectMemoryDetailView,
    ProjectMemoryDraftConfirmView,
    ProjectMemoryDraftListView,
    ProjectMemoryDraftRejectView,
    ProjectMemoryListCreateView,
    ProjectMergeRequestListView,
    ProjectOwnerTransferView,
    ProjectTransitionView,
    ProjectWorkItemDetailView,
    ProjectWorkItemListView,
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
    # 项目记忆（MEM-01~04）
    path(
        "<uuid:project_id>/memories/",
        ProjectMemoryListCreateView.as_view(),
        name="project-memory-list",
    ),
    path(
        "<uuid:project_id>/memories/<uuid:memory_id>/",
        ProjectMemoryDetailView.as_view(),
        name="project-memory-detail",
    ),
    path(
        "<uuid:project_id>/memory-drafts/",
        ProjectMemoryDraftListView.as_view(),
        name="project-memory-draft-list",
    ),
    path(
        "<uuid:project_id>/memory-drafts/<uuid:draft_id>/confirm/",
        ProjectMemoryDraftConfirmView.as_view(),
        name="project-memory-draft-confirm",
    ),
    path(
        "<uuid:project_id>/memory-drafts/<uuid:draft_id>/reject/",
        ProjectMemoryDraftRejectView.as_view(),
        name="project-memory-draft-reject",
    ),
    # MergeRequest（MR-01/02，项目内可见）
    path(
        "<uuid:project_id>/merge-requests/",
        ProjectMergeRequestListView.as_view(),
        name="project-merge-request-list",
    ),
    # 工作项组合（COMPOSE-01/02）
    path(
        "<uuid:project_id>/work-items/",
        ProjectWorkItemListView.as_view(),
        name="project-work-item-list",
    ),
    path(
        "<uuid:project_id>/work-items/<uuid:work_item_id>/",
        ProjectWorkItemDetailView.as_view(),
        name="project-work-item-detail",
    ),
    # Cursor rules 模板（CURSOR-02）
    path(
        "<uuid:project_id>/cursor-rules/",
        ProjectCursorRulesView.as_view(),
        name="project-cursor-rules",
    ),
]
