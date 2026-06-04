---
name: friday-ai
description: "Use when an agent needs to configure Friday AI access, verify Friday MCP connectivity, choose the right Friday skill, or diagnose setup issues before using Friday AI codebase or Feishu workflows."
---
# Friday AI
## Purpose
Use this skill as the entry point for Friday AI. It helps an external agent connect to a Friday AI server, verify credentials, and route the user to the correct workflow skill.
## Required Setup
- `FRIDAY_BASE_URL`: Friday server origin, for example `https://friday.example.com`.
- `FRIDAY_ACCESS_TOKEN`: Friday Access Token created in Friday.
- Network access from the agent environment to `FRIDAY_BASE_URL`.
- Repository credentials configured in Friday before execution or MR creation.
- Feishu credentials configured in Friday before Feishu Project or Feishu Docs workflows.
Every Friday MCP call uses:
```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
```
## Routing
- Use `friday-codebase-agent` when the user starts from a repository coding requirement, asks for codebase analysis, wants a coding plan, wants Friday to execute a plan, or wants PR/MR creation.
- Use `friday-feishu-agent` when the user starts from a Feishu Project work item, board item, requirement, defect, linked Feishu Doc, or wants technical-plan writeback and PR/MR writeback.
## Setup Check
Before running a destructive or expensive workflow:
1. Confirm `FRIDAY_BASE_URL` and `FRIDAY_ACCESS_TOKEN` are present.
2. Call a low-risk MCP read tool relevant to the workflow.
3. Preserve the returned `run_id` and reuse it via `X-Friday-Run-ID` for later workflow calls.
4. If auth fails, ask the user to create or rotate the Friday Access Token.
5. If repository or Feishu credentials are missing, stop before execution and report the missing server-side configuration.
## Guardrails
- Never echo `FRIDAY_ACCESS_TOKEN` or Feishu secrets.
- Do not run repo execution before the selected workflow has a plan and repository route.
- Treat Friday as the source of truth for repository credentials, Feishu credentials, execution traces, and PR/MR writeback state.
- When setup is incomplete, produce a concrete checklist instead of attempting partial execution.
## References
- Codebase workflows: use `friday-codebase-agent`.
- Feishu workflows: use `friday-feishu-agent`.
