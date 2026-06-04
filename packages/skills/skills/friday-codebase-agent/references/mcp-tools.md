# Friday MCP Tool Reference
## Transport
All tools are HTTP POST endpoints:
```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
X-Friday-Run-ID: {run_id from first workflow call, optional on first call}
X-Friday-Skill-Step: {workflow.step, optional}
```
Each successful response includes `run_id`. Use that value as `X-Friday-Run-ID` for later calls in the same Skill workflow.
## Read Tools
| Tool | Use | Request | Response |
| --- | --- | --- | --- |
| `route_repositories` | Rank repositories for a requirement or repo hint. | `query`, `top_k` | `query`, `ranked_repos`, `total`, `run_id` |
| `search_rag_chunks` | Retrieve branch-aware RAG chunks and related edges. | `repository_id`, `query`, `branch`, `top_k`, `max_tokens` | `query`, `repository_id`, `branch`, `results`, `related_edges`, `total_tokens`, `run_id` |
| `get_repository` | Read repository metadata and index status. | `repository_id` | `repository`, `run_id` |
| `list_repository_files` | Browse indexed file paths. | `repository_id`, `branch`, `path`, `recursive`, `page`, `page_size` | `repository_id`, `branch`, `path`, `items`, `total`, `page`, `page_size`, `run_id` |
| `get_repository_file` | Read file content by path and optional line range. | `repository_id`, `file_path`, `branch`, `start_line`, `end_line`, `max_lines` | `repository_id`, `branch`, `file_path`, `content`, `truncated`, `total_chunks`, `returned_lines`, `max_lines`, `run_id` |
| `find_related_chunks` | Expand from a chunk, file path, or symbol. | `repository_id`, `branch`, `chunk_id`, `file_path`, `symbol_name`, `relation_types`, `hops`, `direction`, `limit` | `repository_id`, `branch`, `source`, `related_chunks`, `run_id` |
## Planning Tools
| Tool | Use | Request | Response |
| --- | --- | --- | --- |
| `analyze_repository` | Produce architecture summary, modules, entry points, risks, test strategy, and reading order. | `repository_id`, `branch`, `focus`, `context_chunks`, `max_files` | `analysis_id`, `repository_id`, `branch`, `analysis`, `evidence`, `run_id` |
| `create_coding_plan` | Create a structured coding plan. | `repository_id`, `branch`, `requirement`, `analysis_id`, `context_chunks`, `max_steps` | `plan_id`, `version_id`, `version`, `repository_id`, `branch`, `plan`, `evidence`, `run_id` |
| `improve_coding_plan` | Create a new plan version from feedback. | `plan_id`, `feedback`, `context_chunks`, `max_steps` | `plan_id`, `version_id`, `version`, `repository_id`, `branch`, `plan`, `change_summary`, `risk_delta`, `evidence`, `run_id` |
## Execution And MR Tools
| Tool | Use | Request | Response |
| --- | --- | --- | --- |
| `execute_coding_plan` | Create or validate a branch, dispatch the coding runner, and return an execution trace. | `plan_id`, `version_id`, `branch_name`, `target_branch`, `retry_of_execution_id`, `timeout_seconds` | `execution_id`, `plan_id`, `version_id`, `repository_id`, `status`, `branch_name`, `target_branch`, `coding_session_id`, `subagent_session_id`, `commit_sha`, `file_changes`, `test_results`, `push_result`, `last_diff`, `runner_logs`, `recovery_state`, `dispatch_payload`, `error`, `retry_of_execution_id`, `retry_count`, `run_id` |
| `get_coding_execution` | Refresh and inspect execution status. | `execution_id` | Same fields as `execute_coding_plan` |
| `summarize_branch` | Compare source/target branch, create diff summary and MR draft. | `execution_id`, `repository_id`, `source_branch`, `target_branch`, `max_files` | `execution_id`, `repository_id`, `source_branch`, `target_branch`, `summary`, `mr_draft`, `run_id` |
| `create_merge_request` | Create MR and persist MR result or partial recovery state. | `execution_id`, `repository_id`, `source_branch`, `target_branch`, `title`, `description`, `reviewer_usernames`, `remove_source_branch` | `execution_id`, `repository_id`, `source_branch`, `target_branch`, `mr`, `execution_status`, `run_id` |
## Feishu Work Item Tools
| Tool | Use | Request | Response |
| --- | --- | --- | --- |
| `get_feishu_work_item_context` | Read Feishu work item context, relations, comments, and linked docs. | `project_id`, `project_key`, `work_item_type`, `work_item_id`, `fields`, `include_comments` | `context_id`, `project_id`, `work_item`, `relations`, `documents`, `comments`, `context`, `status`, `run_id` |
| `create_feishu_technical_plan` | Generate a work item technical plan, create Feishu doc, and comment back. | `context_id`, `repository_ids`, `repo_hints`, `context_chunks`, `similar_cases`, `title`, `folder_token`, `create_document`, `write_comment` | `technical_plan_id`, `context_id`, `project_id`, `plan`, `markdown`, `repository_tasks`, `evidence`, `feishu_document`, `comment`, `status`, `retry_state`, `run_id` |
| `create_work_item_repo_tasks` | Create durable repo tasks from a technical plan matrix. | `technical_plan_id` | `technical_plan_id`, `tasks`, `total`, `run_id` |
| `execute_work_item_repo_tasks` | Execute repo tasks through coding execution/MR flow and write results back. | `technical_plan_id`, `task_ids`, `create_missing`, `dispatch`, `create_merge_requests`, `write_back`, `timeout_seconds`, `reviewer_usernames` | `technical_plan_id`, `tasks`, `summary`, `document_update`, `comment`, `status`, `run_id` |
| `create_learning_case` | Persist a reusable LearningCase from technical plan execution results. | `technical_plan_id`, `outcome`, `root_cause`, `solution_notes`, `tests` | `learning_case_id`, `case`, `run_id` |
| `search_learning_cases` | Retrieve similar historical requirements or Bug fixes. | `query`, `work_item_type`, `repo_hints`, `file_hints`, `symbol_hints`, `limit` | `query`, `results`, `total`, `run_id` |
## Errors
Errors use `{ "error_code": "...", "detail": "..." }`.
Common codes:
- `authentication_failed` or `authentication_required`: create or refresh a Friday Access Token.
- `invalid_params`: fix the request shape.
- `repository_not_found`: rerun discovery or verify repository access.
- `repository_not_indexed`: index the repository before GraphRAG or planning.
- `git_platform_error`: check Git credentials, branch existence, permissions, or existing MR state.
