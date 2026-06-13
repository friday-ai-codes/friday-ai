---
status: resolved
trigger: "v0.4.0 UAT blockers found during local browser run"
created: 2026-06-14
updated: 2026-06-14
---

# Debug Session: UAT Blockers

## Symptoms

- Expected behavior: manual-triggered workflows start from `manual_trigger`, render selected `{{nodes.*}}` variables in downstream node config, and fail fast with structured template errors for missing fields.
- Actual behavior: `manual_trigger` failed before downstream nodes with an async ORM lazy-load error.
- Actual behavior: when bypassing `manual_trigger`, `code.config.code` emitted literal `{{nodes.*}}` strings instead of resolved values; missing fields did not fail.
- Error messages:
  - `Failed to parse manual_trigger payload: You cannot call this from an async context - use a thread or sync_to_async.`
  - literal output: `{{nodes.<short_id>.space_name}}`
- Reproduction:
  - Execute a workflow containing `manual_trigger -> fetch_space_info -> code`.
  - Execute a workflow containing `code producer -> code consumer` where consumer code references a missing upstream field.

## Current Focus

- hypothesis: `ManualTriggerNode.parse_payload` lazily loads `workflow_execution.triggered_by` in an async node execution path; `CodeNode.execute` skips `ExecutionContext.render_template` for its `code` config.
- test: Add regression tests for async-safe manual trigger executor metadata and code-node template rendering / missing-field propagation.
- expecting: manual trigger no longer raises `SynchronousOnlyOperation`; code node resolves `{{nodes.*}}` before AST safety and execution; missing fields raise `TemplateResolutionError`.
- next_action: Patch nodes and run targeted workflow node tests, then rerun local UAT paths through the browser/API.

## Evidence

- timestamp: 2026-06-14T01:10:00+08:00
  finding: UAT execution traceback pointed at `server/workflows/nodes/triggers/manual.py` accessing `context.workflow_execution.triggered_by`.
- timestamp: 2026-06-14T01:15:00+08:00
  finding: Direct `fetch_space_info -> code` execution completed with literal template strings in `code` output.

## Resolution

- root_cause: `manual_trigger` 在 async 执行路径访问未缓存的 `triggered_by` FK；`CodeNode` 没有渲染 `config.code` 中的模板变量。
- fix: `manual_trigger` 改用 `triggered_by_id` + async user lookup；`CodeNode` 在 AST 安全检查和执行前调用 `ExecutionContext.render_template`。
- verification: `cd server && uv run pytest tests/workflows/test_code_node.py tests/workflows/test_nodes.py -q` passed; Chrome/API UAT retest passed for completed, failed-template, and suspended workflows.
- files_changed: `server/workflows/nodes/triggers/manual.py`, `server/workflows/nodes/actions/code.py`, `server/tests/workflows/test_code_node.py`, `server/tests/workflows/test_nodes.py`
