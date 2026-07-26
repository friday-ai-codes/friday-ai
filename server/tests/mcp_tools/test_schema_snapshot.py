from __future__ import annotations

import re

from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT

# 三个 feature 方案工具共用的响应键集。**刻意在测试里独立写一份字面量**——从
# serializers 导入同一个常量会让本守卫退化为自我比较，改错源码也照样绿。
_FEATURE_SOLUTION_RESPONSE = [
    "session_id",
    "status",
    "project_id",
    "source",
    "feature_count",
    "truncated",
    "classification",
    "routing",
    "questions",
    "clarification_id",
    "plan",
    "markdown",
    "artifact_version_id",
    "error",
    "run_id",
]


def test_registered_tools_match_snapshot() -> None:
    """注册 == snapshot 防漏守卫（Phase 102 UNIFY-04）。

    从 ``mcp_tools/urls.py`` 的 ``tools/<name>/`` 路由提取工具名集合，断言与
    ``TOOL_SCHEMA_SNAPSHOT`` 键集合完全一致——未来加工具漏 snapshot（或 snapshot
    残留幽灵键）时 CI 直接红且可读。
    """
    from mcp_tools.urls import urlpatterns

    registered: set[str] = set()
    for p in urlpatterns:
        m = re.fullmatch(r"tools/([a-z0-9_]+)/", str(p.pattern))
        if m:
            registered.add(m.group(1))

    snapshot = set(TOOL_SCHEMA_SNAPSHOT)
    missing_in_snapshot = registered - snapshot
    ghost_in_snapshot = snapshot - registered
    assert registered == snapshot, (
        f"注册了但没进 snapshot: {sorted(missing_in_snapshot)}; "
        f"snapshot 残留幽灵键（未注册）: {sorted(ghost_in_snapshot)}"
    )


def test_mcp_read_tool_schema_snapshot() -> None:
    assert TOOL_SCHEMA_SNAPSHOT == {
        "route_repositories": {
            "request": ["query", "top_k"],
            "response": ["query", "ranked_repos", "total", "run_id"],
        },
        "search_rag_chunks": {
            "request": ["repository_id", "repository_ids", "all_repositories", "max_repos", "query", "branch", "top_k", "max_tokens"],
            "response": ["query", "repository_id", "repository_ids", "branch", "results", "related_edges", "total_tokens", "run_id"],
        },
        "get_repository": {
            "request": ["repository_id"],
            "response": ["repository", "run_id"],
        },
        "list_repository_files": {
            "request": ["repository_id", "branch", "path", "recursive", "page", "page_size"],
            "response": ["repository_id", "branch", "path", "items", "total", "page", "page_size", "run_id"],
        },
        "get_repository_file": {
            "request": ["repository_id", "file_path", "branch", "start_line", "end_line", "max_lines"],
            "response": ["repository_id", "branch", "file_path", "content", "truncated", "total_chunks", "returned_lines", "max_lines", "source", "commit_sha", "total_lines", "run_id"],
        },
        "grep_repository": {
            "request": ["repository_id", "repository_ids", "all_repositories", "max_repos", "pattern", "branch", "regex", "case_sensitive", "paths", "include_globs", "exclude_globs", "context_lines", "max_matches", "output_mode", "max_tokens"],
            "response": ["pattern", "output_mode", "repositories", "total_matches", "truncated", "run_id"],
        },
        "find_related_chunks": {
            "request": ["repository_id", "branch", "chunk_id", "file_path", "symbol_name", "relation_types", "hops", "direction", "limit"],
            "response": ["repository_id", "branch", "source", "related_chunks", "run_id"],
        },
        "reverse_lookup_requirements": {
            "request": ["repository_id", "file_path", "line", "chunk_id", "branch"],
            "response": ["chunks", "related_work_items", "related_documents", "paths", "run_id"],
        },
        "analyze_repository": {
            "request": ["repository_id", "branch", "focus", "context_chunks", "max_files"],
            "response": ["analysis_id", "repository_id", "branch", "analysis", "evidence", "run_id"],
        },
        "create_coding_plan": {
            "request": ["repository_id", "branch", "requirement", "analysis_id", "context_chunks", "max_steps"],
            "response": ["plan_id", "version_id", "version", "repository_id", "branch", "plan", "evidence", "run_id", "session_id", "status"],
        },
        "improve_coding_plan": {
            "request": ["plan_id", "feedback", "context_chunks", "max_steps"],
            "response": ["plan_id", "version_id", "version", "repository_id", "branch", "plan", "change_summary", "risk_delta", "evidence", "run_id", "session_id", "status"],
        },
        "execute_coding_plan": {
            "request": ["plan_id", "version_id", "branch_name", "target_branch", "retry_of_execution_id", "timeout_seconds"],
            "response": ["execution_id", "plan_id", "version_id", "repository_id", "status", "branch_name", "target_branch", "coding_session_id", "subagent_session_id", "commit_sha", "file_changes", "test_results", "push_result", "last_diff", "runner_logs", "recovery_state", "dispatch_payload", "error", "retry_of_execution_id", "retry_count", "run_id"],
        },
        "get_coding_execution": {
            "request": ["execution_id"],
            "response": ["execution_id", "plan_id", "version_id", "repository_id", "status", "branch_name", "target_branch", "coding_session_id", "subagent_session_id", "commit_sha", "file_changes", "test_results", "push_result", "last_diff", "runner_logs", "recovery_state", "dispatch_payload", "error", "retry_of_execution_id", "retry_count", "run_id"],
        },
        "summarize_branch": {
            "request": ["execution_id", "repository_id", "source_branch", "target_branch", "max_files"],
            "response": ["execution_id", "repository_id", "source_branch", "target_branch", "summary", "mr_draft", "run_id"],
        },
        "create_merge_request": {
            "request": ["execution_id", "repository_id", "source_branch", "target_branch", "title", "description", "reviewer_usernames", "remove_source_branch"],
            "response": ["execution_id", "repository_id", "source_branch", "target_branch", "mr", "execution_status", "run_id"],
        },
        "get_feishu_work_item_context": {
            "request": ["project_id", "project_key", "work_item_type", "work_item_id", "fields", "include_comments"],
            "response": ["context_id", "project_id", "work_item", "relations", "documents", "comments", "context", "status", "run_id"],
        },
        "create_feishu_technical_plan": {
            "request": ["context_id", "repository_ids", "repo_hints", "context_chunks", "similar_cases", "title", "folder_token", "create_document", "write_comment"],
            "response": ["technical_plan_id", "context_id", "project_id", "plan", "markdown", "repository_tasks", "evidence", "feishu_document", "comment", "status", "retry_state", "run_id"],
        },
        "create_work_item_repo_tasks": {
            "request": ["technical_plan_id"],
            "response": ["technical_plan_id", "tasks", "total", "run_id"],
        },
        "execute_work_item_repo_tasks": {
            "request": ["technical_plan_id", "task_ids", "create_missing", "dispatch", "create_merge_requests", "write_back", "timeout_seconds", "reviewer_usernames"],
            "response": ["technical_plan_id", "tasks", "summary", "document_update", "comment", "status", "run_id"],
        },
        "create_learning_case": {
            "request": ["technical_plan_id", "outcome", "root_cause", "solution_notes", "tests"],
            "response": ["learning_case_id", "case", "run_id"],
        },
        "search_learning_cases": {
            "request": ["query", "work_item_type", "repo_hints", "file_hints", "symbol_hints", "limit"],
            "response": ["query", "results", "total", "run_id"],
        },
        "search_delivery_knowledge": {
            "request": [
                "query",
                "top_k",
                "project_ids",
                "repository_ids",
                "entity_kinds",
                "as_of",
                "include_superseded",
            ],
            "response": ["query", "results", "total", "as_of", "run_id"],
        },
        "get_entity_timeline": {
            "request": ["entity_id", "include_superseded", "as_of"],
            "response": ["entity_id", "nodes", "total", "run_id"],
        },
        "get_related_entities": {
            "request": ["entity_id", "direction", "max_hops", "as_of"],
            "response": ["entity_id", "related", "total", "as_of", "run_id"],
        },
        "lookup_project_by_branch": {
            "request": ["branch_name", "repository_id"],
            "response": [
                "branch_name",
                "work_item_id",
                "repository_id",
                "matched",
                "project",
                "candidates",
                "context",
                "included_layers",
                "run_id",
            ],
        },
        "report_project_knowledge": {
            "request": ["project_id", "content", "source_conversation_id"],
            "response": ["accepted", "draft_id", "reason", "run_id"],
        },
        "report_project_state": {
            "request": ["project_id", "branch_name", "repository_id", "apis"],
            "response": ["applied", "reason", "results", "total_applied", "run_id"],
        },
        "search_project_context": {
            "request": ["project_id", "query", "top_k", "entity_kinds"],
            "response": ["project_id", "query", "results", "total", "run_id"],
        },
        "grep_project": {
            "request": ["project_id", "query", "top_k"],
            "response": ["project_id", "query", "results", "total", "run_id"],
        },
        "read_project_doc": {
            "request": ["project_id", "doc_type"],
            "response": ["project_id", "doc_type", "rendered_markdown", "blocks", "run_id"],
        },
        "create_feature_tech_plan": {
            "request": [
                "project_id",
                "branch_name",
                "repository_id",
                "feature_list_text",
                "repository_ids",
            ],
            "response": _FEATURE_SOLUTION_RESPONSE,
        },
        "confirm_feature_tech_plan": {
            "request": ["session_id", "answers"],
            "response": _FEATURE_SOLUTION_RESPONSE,
        },
        "get_feature_tech_plan": {
            "request": ["session_id"],
            "response": _FEATURE_SOLUTION_RESPONSE,
        },
    }
