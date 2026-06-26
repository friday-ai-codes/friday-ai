"""MCP read tools URLConf."""

from django.urls import path

from .views import (
    AnalyzeRepositoryView,
    CreateCodingPlanView,
    CreateFeishuTechnicalPlanView,
    CreateLearningCaseView,
    CreateMergeRequestView,
    CreateWorkItemRepoTasksView,
    ExecuteCodingPlanView,
    ExecuteWorkItemRepoTasksView,
    FindRelatedChunksView,
    GetCodingExecutionView,
    GetEntityTimelineView,
    GetFeishuWorkItemContextView,
    GetRelatedEntitiesView,
    GetRepositoryFileView,
    GetRepositoryView,
    GrepProjectView,
    GrepRepositoryView,
    ImproveCodingPlanView,
    ListRepositoryFilesView,
    LookupProjectByBranchView,
    ReadProjectDocView,
    ReportProjectKnowledgeView,
    ReportProjectStateView,
    ReverseLookupView,
    RouteRepositoriesView,
    SearchDeliveryKnowledgeView,
    SearchLearningCasesView,
    SearchProjectContextView,
    SearchRagChunksView,
    SummarizeBranchView,
)

urlpatterns = [
    path("tools/route_repositories/", RouteRepositoriesView.as_view(), name="mcp-tool-route-repositories"),
    path("tools/search_rag_chunks/", SearchRagChunksView.as_view(), name="mcp-tool-search-rag-chunks"),
    path("tools/get_repository/", GetRepositoryView.as_view(), name="mcp-tool-get-repository"),
    path("tools/list_repository_files/", ListRepositoryFilesView.as_view(), name="mcp-tool-list-repository-files"),
    path("tools/get_repository_file/", GetRepositoryFileView.as_view(), name="mcp-tool-get-repository-file"),
    path("tools/grep_repository/", GrepRepositoryView.as_view(), name="mcp-tool-grep-repository"),
    path("tools/find_related_chunks/", FindRelatedChunksView.as_view(), name="mcp-tool-find-related-chunks"),
    path("tools/reverse_lookup_requirements/", ReverseLookupView.as_view(), name="mcp-tool-reverse-lookup-requirements"),
    path("tools/analyze_repository/", AnalyzeRepositoryView.as_view(), name="mcp-tool-analyze-repository"),
    path("tools/create_coding_plan/", CreateCodingPlanView.as_view(), name="mcp-tool-create-coding-plan"),
    path("tools/improve_coding_plan/", ImproveCodingPlanView.as_view(), name="mcp-tool-improve-coding-plan"),
    path("tools/execute_coding_plan/", ExecuteCodingPlanView.as_view(), name="mcp-tool-execute-coding-plan"),
    path("tools/get_coding_execution/", GetCodingExecutionView.as_view(), name="mcp-tool-get-coding-execution"),
    path("tools/summarize_branch/", SummarizeBranchView.as_view(), name="mcp-tool-summarize-branch"),
    path("tools/create_merge_request/", CreateMergeRequestView.as_view(), name="mcp-tool-create-merge-request"),
    path("tools/get_feishu_work_item_context/", GetFeishuWorkItemContextView.as_view(), name="mcp-tool-get-feishu-work-item-context"),
    path("tools/create_feishu_technical_plan/", CreateFeishuTechnicalPlanView.as_view(), name="mcp-tool-create-feishu-technical-plan"),
    path("tools/create_work_item_repo_tasks/", CreateWorkItemRepoTasksView.as_view(), name="mcp-tool-create-work-item-repo-tasks"),
    path("tools/execute_work_item_repo_tasks/", ExecuteWorkItemRepoTasksView.as_view(), name="mcp-tool-execute-work-item-repo-tasks"),
    path("tools/create_learning_case/", CreateLearningCaseView.as_view(), name="mcp-tool-create-learning-case"),
    path("tools/search_learning_cases/", SearchLearningCasesView.as_view(), name="mcp-tool-search-learning-cases"),
    path(
        "tools/search_delivery_knowledge/",
        SearchDeliveryKnowledgeView.as_view(),
        name="mcp-tool-search-delivery-knowledge",
    ),
    path(
        "tools/get_entity_timeline/",
        GetEntityTimelineView.as_view(),
        name="mcp-tool-get-entity-timeline",
    ),
    path(
        "tools/get_related_entities/",
        GetRelatedEntitiesView.as_view(),
        name="mcp-tool-get-related-entities",
    ),
    # Cursor 回流（CURSOR-01/03）
    path(
        "tools/lookup_project_by_branch/",
        LookupProjectByBranchView.as_view(),
        name="mcp-tool-lookup-project-by-branch",
    ),
    path(
        "tools/report_project_knowledge/",
        ReportProjectKnowledgeView.as_view(),
        name="mcp-tool-report-project-knowledge",
    ),
    # STATE 结构化回写（HOOK-03，Phase 86-04）
    path(
        "tools/report_project_state/",
        ReportProjectStateView.as_view(),
        name="mcp-tool-report-project-state",
    ),
    # 项目上下文读半（CTX-01/02，Phase 85-02）
    path(
        "tools/search_project_context/",
        SearchProjectContextView.as_view(),
        name="mcp-tool-search-project-context",
    ),
    path(
        "tools/grep_project/",
        GrepProjectView.as_view(),
        name="mcp-tool-grep-project",
    ),
    path(
        "tools/read_project_doc/",
        ReadProjectDocView.as_view(),
        name="mcp-tool-read-project-doc",
    ),
]
