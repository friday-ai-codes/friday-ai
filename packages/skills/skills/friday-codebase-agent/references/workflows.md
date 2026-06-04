# Friday Codebase Agent Workflows
## Shared State
Keep these values in memory during any workflow:
- `workflow_run_id`: first successful tool response `run_id`.
- `repository_id` and `branch`.
- `analysis_id`.
- `plan_id` and `version_id`.
- `execution_id`, `branch_name`, `target_branch`, `commit_sha`, and `push_result`.
- `mr_url` or `recovery_state`.
After the first response, every call includes:
```text
X-Friday-Run-ID: {workflow_run_id}
X-Friday-Skill-Step: {workflow.step}
```
## discover
Use when the user provides a requirement, repository hint, or natural language target.
1. `route_repositories` with the user text.
2. Select the top repository if confidence is clear.
3. `get_repository` for metadata and index status.
4. Optionally `list_repository_files` for a shallow file-tree scan.
Output: `repository_id`, default branch, index status, route reason, and `workflow_run_id`.
## analyze
Use when the repository is known and the user wants implementation context.
1. `search_rag_chunks` with the requirement or focus.
2. `find_related_chunks` for important files, chunks, or symbols.
3. `analyze_repository` with selected context chunks.
Output: `analysis_id`, architecture summary, key modules, risks, test strategy, evidence IDs, and `workflow_run_id`.
## plan
Use when the user wants a concrete implementation plan.
1. Ensure `repository_id` exists; run `discover` first if needed.
2. Ensure analysis exists; run `analyze` if the change is non-trivial.
3. `create_coding_plan` with requirement, `analysis_id`, and context chunks.
Output: `plan_id`, `version_id`, implementation steps, affected files, tests, risks, and `workflow_run_id`.
## improve
Use when the user or reviewer gives feedback on an existing plan.
1. `improve_coding_plan` with `plan_id`, feedback, and any new context chunks.
2. Compare `change_summary` and `risk_delta`.
3. Use the newest `version_id` for execution unless the user selects an older version.
Output: new `version_id`, updated plan, change summary, risk delta, and `workflow_run_id`.
## execute
Use when a plan is approved or the user asks Friday to make the change.
1. `execute_coding_plan` with `plan_id`, optional `version_id`, branch, target branch, and timeout.
2. Poll `get_coding_execution` until status is `completed`, `failed`, or `partial`.
3. If completed with pushed branch, call `summarize_branch`.
4. If MR creation is desired, call `create_merge_request` using `execution_id` and the MR draft.
Output: `execution_id`, status, branch, commit, push result, test results, MR result or recovery state, and `workflow_run_id`.
## full_auto
Use when the user provides a concrete coding requirement and expects Friday to handle the work end to end.
1. `route_repositories` with the full requirement.
2. `get_repository` for the selected repo.
3. `search_rag_chunks` for requirement-specific evidence.
4. `find_related_chunks` for key chunks/files when the initial evidence names entry points.
5. `analyze_repository` with selected evidence.
6. `create_coding_plan`.
7. If the plan exposes an obvious gap, call `improve_coding_plan` once with precise feedback.
8. `execute_coding_plan`.
9. Poll `get_coding_execution`.
10. `summarize_branch`.
11. `create_merge_request`.
12. Return final trace details and any recovery action.
Stop early only when repository selection is ambiguous, the repository is not indexed, execution fails without a retryable recovery state, or MR creation returns a non-retryable platform error.
## Recovery
- `repository_not_indexed`: report the repo and branch; ask for indexing before planning/execution.
- Execution `failed`: return `execution_id`, `error`, `runner_logs`, `last_diff`, and `recovery_state`; retry with `retry_of_execution_id` only if recovery is marked retryable.
- Execution `partial`: code was pushed but a later step failed; do not rerun code blindly. Prefer retrying `summarize_branch` or `create_merge_request`.
- MR failure after push: preserve source branch, target branch, commit sha, and `mr_error`; retry MR creation after platform issue is fixed.
