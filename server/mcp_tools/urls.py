"""MCP read tools URLConf."""
from django.urls import path
from .views import (
 AnalyzeRepositoryView,
 CreateCodingPlanView,
 CreateMergeRequestView,
 ExecuteCodingPlanView,
 FindRelatedChunksView,
 GetCodingExecutionView,
 GetFeishuWorkItemContextView,
 GetRepositoryFileView,
 GetRepositoryView,
 ImproveCodingPlanView,
 ListRepositoryFilesView,
 RouteRepositoriesView,
 SearchRagChunksView,
 SummarizeBranchView,
)
urlpatterns = [
 path("tools/route_repositories/", RouteRepositoriesView.as_view, name="mcp-tool-route-repositories"),
 path("tools/search_rag_chunks/", SearchRagChunksView.as_view, name="mcp-tool-search-rag-chunks"),
 path("tools/get_repository/", GetRepositoryView.as_view, name="mcp-tool-get-repository"),
 path("tools/list_repository_files/", ListRepositoryFilesView.as_view, name="mcp-tool-list-repository-files"),
 path("tools/get_repository_file/", GetRepositoryFileView.as_view, name="mcp-tool-get-repository-file"),
 path("tools/find_related_chunks/", FindRelatedChunksView.as_view, name="mcp-tool-find-related-chunks"),
 path("tools/analyze_repository/", AnalyzeRepositoryView.as_view, name="mcp-tool-analyze-repository"),
 path("tools/create_coding_plan/", CreateCodingPlanView.as_view, name="mcp-tool-create-coding-plan"),
 path("tools/improve_coding_plan/", ImproveCodingPlanView.as_view, name="mcp-tool-improve-coding-plan"),
 path("tools/execute_coding_plan/", ExecuteCodingPlanView.as_view, name="mcp-tool-execute-coding-plan"),
 path("tools/get_coding_execution/", GetCodingExecutionView.as_view, name="mcp-tool-get-coding-execution"),
 path("tools/summarize_branch/", SummarizeBranchView.as_view, name="mcp-tool-summarize-branch"),
 path("tools/create_merge_request/", CreateMergeRequestView.as_view, name="mcp-tool-create-merge-request"),
 path("tools/get_feishu_work_item_context/", GetFeishuWorkItemContextView.as_view, name="mcp-tool-get-feishu-work-item-context"),
]
