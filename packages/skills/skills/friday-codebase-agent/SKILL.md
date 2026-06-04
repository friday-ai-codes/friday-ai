---
name: friday-codebase-agent
description: "Use when an agent needs Friday AI repository coding workflows: discover repositories, inspect GraphRAG evidence, analyze a codebase, create or improve coding plans, execute a plan, summarize a branch, create a merge request, or run full_auto from requirement text to traced MR."
---
# Friday Codebase Agent
## Overview
Use this skill to drive Friday AI's external repository-coding toolchain through the Friday MCP HTTP tools. It turns a user requirement into a traceable sequence of repository discovery, GraphRAG retrieval, analysis, planning, execution, branch summary, and merge request creation.
## Required Setup
- `FRIDAY_BASE_URL`: Friday server origin, for example `https://friday.example.com`.
- `FRIDAY_ACCESS_TOKEN`: Friday Access Token created in the Friday profile page.
- Every tool call is `POST {FRIDAY_BASE_URL}/api/mcp/tools/{tool_name}/` with `Authorization: Bearer {FRIDAY_ACCESS_TOKEN}`.
- On the first call, store the returned `run_id`. On every later call in the same workflow, pass `X-Friday-Run-ID: {run_id}` and `X-Friday-Skill-Step: {workflow.step}`.
## Workflow Selection
- `discover`: find the right repository and confirm index health.
- `analyze`: retrieve GraphRAG evidence and produce architecture/risk/test context.
- `plan`: create a structured coding plan from requirement + evidence.
- `improve`: revise an existing plan from feedback or review concerns.
- `execute`: run a selected plan, poll execution trace, then summarize/create MR when ready.
- `full_auto`: run discover -> analyze -> plan -> execute -> summarize -> create MR without stopping unless repository confidence is too low or execution becomes unrecoverable.
Prefer `full_auto` when the user gives a concrete coding requirement and asks Friday to handle the work end to end. Prefer the narrower workflows when the user asks only for planning, analysis, execution, or MR creation.
## Trace Discipline
- Treat the first response `run_id` as the workflow trace id.
- Include `X-Friday-Run-ID` on all later tool calls in that workflow.
- Include `X-Friday-Skill-Step` with stable names such as `full_auto.route`, `full_auto.plan`, or `execute.poll`.
- Preserve `repository_id`, `analysis_id`, `plan_id`, `version_id`, and `execution_id` in the agent's working state.
- Report the final `run_id`, `execution_id`, branch, commit, push status, and MR URL or recovery action.
## Guardrails
- Do not create a merge request unless execution produced a pushed branch or the user explicitly supplied a source branch.
- If route scores are weak or multiple repositories are equally plausible, ask one concise clarification before execution. If the user requested autonomous mode, choose the best-ranked repository and log the decision.
- If `create_merge_request` returns `success: false` with `execution_status: partial`, keep the branch and commit information; retry MR creation only after the reported platform issue is addressed.
- Never echo the Friday Access Token. Redact it in notes, logs, and examples.
## References
- For exact tool request/response fields, read [references/mcp-tools.md](references/mcp-tools.md).
- For workflow step order and recovery behavior, read [references/workflows.md](references/workflows.md).
- For example prompts and external agent configuration, read [references/examples.md](references/examples.md).
- For end-to-end acceptance testing, read [references/uat.md](references/uat.md).
