---
title: Friday Codebase Agent
---
# Friday Codebase Agent
`friday-codebase-agent` is a repo-local Codex Skill for using Friday's MCP HTTP tools as an end-to-end codebase agent. It supports repository discovery, GraphRAG analysis, coding plan creation, plan improvement, coding execution, branch summary, and merge request creation.
## Configuration
Create a Friday Access Token from the profile page, then configure:
```bash
export FRIDAY_BASE_URL="https://friday.example.com"
export FRIDAY_ACCESS_TOKEN="friday_pat_redacted"
```
All calls use:
```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
```
For multi-step Skill workflows, keep the first response `run_id` and send it on later calls:
```text
X-Friday-Run-ID: {run_id}
X-Friday-Skill-Step: full_auto.plan
```
This keeps the workflow in one Interaction Ledger trace.
## Workflows
| Workflow | Purpose |
| --- | --- |
| `discover` | Route a requirement to candidate repositories and inspect index health. |
| `analyze` | Retrieve GraphRAG evidence and produce architecture/risk/test context. |
| `plan` | Create a structured coding plan from requirement and evidence. |
| `improve` | Create a revised plan version from feedback. |
| `execute` | Run an approved plan, poll execution, summarize branch, and optionally create an MR. |
| `full_auto` | Run requirement -> repository -> GraphRAG -> plan -> execution -> MR -> trace report. |
## Tool Set
Read tools:
- `route_repositories`
- `search_rag_chunks`
- `get_repository`
- `list_repository_files`
- `get_repository_file`
- `find_related_chunks`
Planning tools:
- `analyze_repository`
- `create_coding_plan`
- `improve_coding_plan`
Execution and MR tools:
- `execute_coding_plan`
- `get_coding_execution`
- `summarize_branch`
- `create_merge_request`
## Recovery
- If repository routing is ambiguous, rerun `discover` with a stronger hint.
- If the repository is not indexed, index it before GraphRAG, planning, or execution.
- If execution fails, inspect `get_coding_execution` for `runner_logs`, `last_diff`, and `recovery_state`.
- If execution is `partial`, code was pushed but a later step failed. Prefer retrying `summarize_branch` or `create_merge_request` instead of rerunning code.
- If MR creation fails, use the persisted branch, target branch, commit sha, and `mr_error` to retry after fixing platform permissions or existing MR state.
## Audit
Use the final `run_id` to inspect `InteractionRun`, `InteractionEvent`, `ToolCallRecord`, `RetrievalTrace`, model usage, execution trace, and MR result records. The workflow should show `skill_step` events plus all MCP tool calls under the same `run_id`.
