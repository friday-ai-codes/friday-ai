"""MCP read tools URLConf."""

from django.urls import path

from .views import (
    AnalyzeRepositoryView,
    AnswerBlueprintClarificationView,
    ApplyRepoAssociationView,
    ConfirmFeatureTechPlanView,
    CreateCodingPlanView,
    CreateFeatureTechPlanView,
    CreateFeishuTechnicalPlanView,
    CreateLearningCaseView,
    CreateMergeRequestView,
    CreateWorkItemRepoTasksView,
    ExecuteCodingPlanView,
    ExecuteWorkItemRepoTasksView,
    FindRelatedChunksView,
    GenerateRequirementSpecView,
    GetCodingExecutionView,
    GetEntityTimelineView,
    GetFeatureTechPlanView,
    GetFeishuWorkItemContextView,
    GetRelatedEntitiesView,
    GetRepoResearchView,
    GetRepositoryFileView,
    GetRepositoryView,
    GetTechnicalBlueprintView,
    GrepProjectView,
    GrepRepositoryView,
    ImpactAnalysisView,
    ImproveCodingPlanView,
    ListRepositoryFilesView,
    LookupProjectByBranchView,
    ReadBlueprintContextView,
    ReadProjectDocView,
    ReportBlueprintContextView,
    ReportProjectKnowledgeView,
    ReportProjectStateView,
    ReverseLookupView,
    RouteBlueprintReposView,
    RouteRepositoriesView,
    SearchDeliveryKnowledgeView,
    SearchLearningCasesView,
    SearchProjectContextView,
    SearchRagChunksView,
    StartRepoResearchView,
    SummarizeBranchView,
    TraceCallPathView,
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
    path("tools/impact_analysis/", ImpactAnalysisView.as_view(), name="mcp-tool-impact-analysis"),
    path("tools/trace_call_path/", TraceCallPathView.as_view(), name="mcp-tool-trace-call-path"),
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
    # feature list 技术方案（两段式：create 出待确认项 → confirm 提交确认 → get 轮询取方案）
    path(
        "tools/create_feature_tech_plan/",
        CreateFeatureTechPlanView.as_view(),
        name="mcp-tool-create-feature-tech-plan",
    ),
    path(
        "tools/confirm_feature_tech_plan/",
        ConfirmFeatureTechPlanView.as_view(),
        name="mcp-tool-confirm-feature-tech-plan",
    ),
    path(
        "tools/get_feature_tech_plan/",
        GetFeatureTechPlanView.as_view(),
        name="mcp-tool-get-feature-tech-plan",
    ),
    # 蓝图共享上下文总线（BUS-01，Phase 113-02）：容器凭任务 token 会话内读写
    path(
        "tools/read_blueprint_context/",
        ReadBlueprintContextView.as_view(),
        name="mcp-tool-read-blueprint-context",
    ),
    path(
        "tools/report_blueprint_context/",
        ReportBlueprintContextView.as_view(),
        name="mcp-tool-report-blueprint-context",
    ),
    # 蓝图异步澄清协议（GATE-01，Phase 116-06）：立即返回 pending → 作答 → 续取终稿。
    # ⛔ 不建第三个 list 工具（pending 清单内联在 get_technical_blueprint 里）。
    path(
        "tools/get_technical_blueprint/",
        GetTechnicalBlueprintView.as_view(),
        name="mcp-tool-get-technical-blueprint",
    ),
    path(
        "tools/answer_blueprint_clarification/",
        AnswerBlueprintClarificationView.as_view(),
        name="mcp-tool-answer-blueprint-clarification",
    ),
    # 蓝图环节单跑（stage sandbox）家族：路由 / 规格 / 调研可基于上游产物单独触发；
    # 前四个为 dry-run / 只读提案面，apply_repo_association 是唯一的采纳写回路径。
    path(
        "tools/route_blueprint_repos/",
        RouteBlueprintReposView.as_view(),
        name="mcp-tool-route-blueprint-repos",
    ),
    path(
        "tools/generate_requirement_spec/",
        GenerateRequirementSpecView.as_view(),
        name="mcp-tool-generate-requirement-spec",
    ),
    path(
        "tools/start_repo_research/",
        StartRepoResearchView.as_view(),
        name="mcp-tool-start-repo-research",
    ),
    path(
        "tools/get_repo_research/",
        GetRepoResearchView.as_view(),
        name="mcp-tool-get-repo-research",
    ),
    path(
        "tools/apply_repo_association/",
        ApplyRepoAssociationView.as_view(),
        name="mcp-tool-apply-repo-association",
    ),
]
