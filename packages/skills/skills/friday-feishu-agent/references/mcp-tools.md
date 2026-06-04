# Friday Feishu MCP Tool Reference
## Core Work Item Tools
| Tool | Use | Request | Response |
| --- | --- | --- | --- |
| `get_feishu_work_item_context` | Read a Feishu work item, relations, comments, linked docs, and persist `McpWorkItemContext`. | `project_id`, `project_key`, `work_item_type`, `work_item_id`, `fields`, `include_comments` | `context_id`, `project_id`, `work_item`, `relations`, `documents`, `comments`, `context`, `status`, `run_id` |
| `create_feishu_technical_plan` | Generate technical plan, create Feishu doc, comment back to work item, and persist `McpWorkItemTechnicalPlan`. | `context_id`, `repository_ids`, `repo_hints`, `context_chunks`, `similar_cases`, `title`, `folder_token`, `create_document`, `write_comment` | `technical_plan_id`, `context_id`, `project_id`, `plan`, `markdown`, `repository_tasks`, `evidence`, `feishu_document`, `comment`, `status`, `retry_state`, `run_id` |
| `create_work_item_repo_tasks` | Fan out technical plan matrix into durable repo tasks. | `technical_plan_id` | `technical_plan_id`, `tasks`, `total`, `run_id` |
| `execute_work_item_repo_tasks` | Execute repo tasks through existing coding execution/MR flow and write results back. | `technical_plan_id`, `task_ids`, `create_missing`, `dispatch`, `create_merge_requests`, `write_back`, `timeout_seconds`, `reviewer_usernames` | `technical_plan_id`, `tasks`, `summary`, `document_update`, `comment`, `status`, `run_id` |
## Learning Tools
| Tool | Use | Request | Response |
| --- | --- | --- | --- |
| `create_learning_case` | Create searchable memory from a technical plan and repo task outcomes. | `technical_plan_id`, `outcome`, `root_cause`, `solution_notes`, `tests` | `learning_case_id`, `case`, `run_id` |
| `search_learning_cases` | Retrieve similar historical fixes or implementations. | `query`, `work_item_type`, `repo_hints`, `file_hints`, `symbol_hints`, `limit` | `query`, `results`, `total`, `run_id` |
## Supporting Codebase Tools
- `route_repositories`
- `search_rag_chunks`
- `get_repository`
- `list_repository_files`
- `get_repository_file`
- `find_related_chunks`
- `analyze_repository`
- `create_coding_plan`
- `execute_coding_plan`
- `get_coding_execution`
- `summarize_branch`
- `create_merge_request`
Use the supporting tools when repository routing, GraphRAG evidence, direct coding-plan execution, or MR retry needs more detail than the work-item workflow tools provide.
## Error Handling
Errors use `{ "error_code": "...", "detail": "..." }`.
- `work_item_context_not_found`: rerun `fetch_context`.
- `technical_plan_not_found`: rerun `plan` or verify `technical_plan_id`.
- `repo_task_matrix_empty`: plan did not identify repositories; rerun `plan` with `repository_ids` or `repo_hints`.
- `repository_not_found`: verify repository is configured in Friday.
- `git_platform_error`: check Git credential, branch, permission, or existing MR state.
- Partial statuses preserve artifacts and retry state; do not discard successful repo tasks.
