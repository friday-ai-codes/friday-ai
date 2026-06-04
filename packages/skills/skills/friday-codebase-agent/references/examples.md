# Friday Codebase Agent Examples
## User Prompts
```text
Use $friday-codebase-agent full_auto to implement: add pagination to the repository file list API and open a merge request.
```
```text
Use $friday-codebase-agent to analyze the billing repository for how usage limits are enforced. Do not execute code yet.
```
```text
Use $friday-codebase-agent improve on plan 9f0c...: reduce migration risk and add a rollback test.
```
```text
Use $friday-codebase-agent execute plan 9f0c... version e12a..., then create an MR if the branch is pushed.
```
## Minimal HTTP Call
```bash
curl -sS "$FRIDAY_BASE_URL/api/mcp/tools/route_repositories/" \
 -H "Authorization: Bearer $FRIDAY_ACCESS_TOKEN" \
 -H "Content-Type: application/json" \
 -H "X-Friday-Skill-Step: full_auto.route" \
 -d '{"query":"add pagination to repository file list","top_k":3}'
```
Then reuse the returned `run_id`:
```bash
curl -sS "$FRIDAY_BASE_URL/api/mcp/tools/create_coding_plan/" \
 -H "Authorization: Bearer $FRIDAY_ACCESS_TOKEN" \
 -H "Content-Type: application/json" \
 -H "X-Friday-Run-ID: $WORKFLOW_RUN_ID" \
 -H "X-Friday-Skill-Step: full_auto.plan" \
 -d '{"repository_id":"...","requirement":"add pagination to repository file list","analysis_id":"..."}'
```
## External Agent Configuration
Use this shape for agents that can call HTTP tools through an adapter:
```json
{
 "friday_codebase_agent": {
 "base_url_env": "FRIDAY_BASE_URL",
 "token_env": "FRIDAY_ACCESS_TOKEN",
 "tool_endpoint": "/api/mcp/tools/{tool_name}/",
 "auth": {
 "type": "bearer",
 "header": "Authorization"
 },
 "trace_headers": {
 "run_id": "X-Friday-Run-ID",
 "skill_step": "X-Friday-Skill-Step"
 }
 }
}
```
For tools that support MCP-style server configuration, wrap the HTTP endpoint with an adapter that maps a tool call named `{tool_name}` to `POST /api/mcp/tools/{tool_name}/` and injects the token and trace headers.
## Final Report Shape
Return:
```text
Repository: <name> (<repository_id>)
Trace: <workflow_run_id>
Plan: <plan_id> version <version_id>
Execution: <execution_id> status <status>
Branch: <branch_name> -> <target_branch>
Commit: <commit_sha or none>
Push: <pushed/failed/skipped>
MR: <mr_url or recovery action>
Tests: <test summary or runner logs pointer>
```
