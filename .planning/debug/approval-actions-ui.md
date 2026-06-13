---
status: resolved
trigger: "Execution detail shows waiting approval but cannot approve from execution pages"
created: 2026-06-14
updated: 2026-06-14
---

# Debug Session: Approval Actions UI

## Symptoms

- Expected behavior: when a workflow execution is suspended on `human_approval`, execution list/detail surfaces should let the current user approve or reject the waiting node.
- Actual behavior: execution detail shows `挂起中` / `等待人工审批`, but no approval action is available.
- Reproduction: open `/executions/1d44499d-10c0-489e-951e-dffe8fdd1adb`.

## Current Focus

- hypothesis: backend node approval endpoints exist, but execution detail UI renders waiting status without action controls.
- test: inspect API/store/component wiring, add UI action if missing, then approve/reject a waiting execution in Chrome.
- expecting: execution detail displays approve/reject controls for `waiting_approval` node executions and calls the existing node execution endpoints.
- next_action: inspect execution page, execution components, and `useExecutionsStore`.

## Evidence

## Resolution

- root_cause: `human_approval` 节点只有等待状态展示；执行详情页的审批操作面板只覆盖 `ai_plan_approval`，列表页也没有把 suspended 待审批执行暴露成可处理入口。
- fix: added `HumanApprovalPanel` for `human_approval` waiting/completed states, wired it into `NodeDetailSheet`, auto-opened the waiting approval sheet on execution detail, and updated execution list status/filter/action rendering for waiting approvals.
- verification: `pnpm type-check` passed; `pnpm test:unit src/components/execution/__tests__/HumanApprovalPanel.spec.ts src/pages/executions/__tests__/index.spec.ts --run` passed; Chrome verified detail URL auto-opens `拒绝`/`通过` and list shows `待审批`/`处理审批`.
- files_changed: `web/src/components/execution/HumanApprovalPanel.vue`, `web/src/components/execution/NodeDetailSheet.vue`, `web/src/components/execution/__tests__/HumanApprovalPanel.spec.ts`, `web/src/pages/executions/[id].vue`, `web/src/pages/executions/index.vue`
