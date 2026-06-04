from __future__ import annotations
from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT
def test_mcp_read_tool_schema_snapshot -> None:
 assert TOOL_SCHEMA_SNAPSHOT == {
 "route_repositories": {
 "request": ["query", "top_k"],
 "response": ["query", "ranked_repos", "total", "run_id"],
 },
 "search_rag_chunks": {
 "request": ["repository_id", "query", "branch", "top_k", "max_tokens"],
 "response": ["query", "repository_id", "branch", "results", "related_edges", "total_tokens", "run_id"],
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
 "response": ["repository_id", "branch", "file_path", "content", "truncated", "total_chunks", "returned_lines", "max_lines", "run_id"],
 },
 "find_related_chunks": {
 "request": ["repository_id", "branch", "chunk_id", "file_path", "symbol_name", "relation_types", "hops", "direction", "limit"],
 "response": ["repository_id", "branch", "source", "related_chunks", "run_id"],
 },
 "analyze_repository": {
 "request": ["repository_id", "branch", "focus", "context_chunks", "max_files"],
 "response": ["analysis_id", "repository_id", "branch", "analysis", "evidence", "run_id"],
 },
 "create_coding_plan": {
 "request": ["repository_id", "branch", "requirement", "analysis_id", "context_chunks", "max_steps"],
 "response": ["plan_id", "version_id", "version", "repository_id", "branch", "plan", "evidence", "run_id"],
 },
 "improve_coding_plan": {
 "request": ["plan_id", "feedback", "context_chunks", "max_steps"],
 "response": ["plan_id", "version_id", "version", "repository_id", "branch", "plan", "change_summary", "risk_delta", "evidence", "run_id"],
 },
 }
