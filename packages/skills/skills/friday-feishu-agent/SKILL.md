---
name: friday-feishu-agent
description: "Use when an agent needs to start from a Feishu Project work item, read linked Feishu Docs, generate a technical plan, fan out multi-repo execution, write PR/MR results back, and create searchable LearningCase memory."
---
# Friday Feishu Agent
## Overview
Use this skill when the user gives a Feishu Project work item URL/ID or asks Friday to process a Feishu requirement/Bug end to end. The execution unit is a Feishu work item. Boards are only entry views or filters.
The skill drives deterministic Friday MCP tools to:
1. fetch work item context and linked docs;
2. generate and write back a technical plan document;
3. create one or more repo tasks;
4. execute tasks through the existing coding runner and MR flow;
5. write execution results back to Feishu;
6. create/search LearningCase memory for future similar work.
## Required Setup
- `FRIDAY_BASE_URL`: Friday server origin.
- `FRIDAY_ACCESS_TOKEN`: Friday Access Token.
- Feishu Project credentials configured on the Friday project or system settings.
- Feishu Docs app credentials and `feishu_doc_folder_token` configured when document creation/writeback is needed.
- Repository indexes and Git credentials configured before execution/MR creation.
All calls are HTTP POST:
```text
POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/
Authorization: Bearer {FRIDAY_ACCESS_TOKEN}
Content-Type: application/json
X-Friday-Run-ID: {run_id from first workflow call, optional on first call}
X-Friday-Skill-Step: {workflow.step, optional}
```
## Workflow Selection
- `fetch_context`: read one Feishu work item and linked docs.
- `plan`: generate a technical plan document and write it back to the work item.
- `execute`: create repo tasks, dispatch coding execution, summarize branches, create PR/MR, and write results back.
- `learn`: create or search LearningCase records.
- `full_auto`: run fetch_context -> plan -> execute -> learn under one `run_id`.
Prefer `full_auto` when the user asks Friday to handle a concrete Feishu requirement or Bug autonomously. Use narrower workflows when the user only needs context, planning, execution, or historical recall.
## Trace Discipline
- Store the first response `run_id`.
- Send `X-Friday-Run-ID` on every later tool call in the same workflow.
- Send stable `X-Friday-Skill-Step` values such as `full_auto.fetch_context`, `full_auto.plan`, `full_auto.execute`, and `full_auto.learn`.
- Preserve `context_id`, `technical_plan_id`, `task_id`, `execution_id`, `learning_case_id`, branch names, commit SHAs, and PR/MR URLs in the final report.
## Guardrails
- Do not execute repo tasks until the technical plan includes a repository task matrix.
- If document creation fails but plan generation succeeds, continue with `partial` status and report retry state.
- If one repo task fails, continue other repo tasks and preserve partial success.
- Do not retry coding execution blindly when only MR creation failed; retry MR creation using the persisted branch/commit.
- Never expose the Friday Access Token, Feishu plugin secret, app secret, or raw credential payloads.
## References
- Tool contracts: [references/mcp-tools.md](references/mcp-tools.md)
- Workflow order and recovery: [references/workflows.md](references/workflows.md)
- Example prompts and requests: [references/examples.md](references/examples.md)
- UAT checklist: [references/uat.md](references/uat.md)
