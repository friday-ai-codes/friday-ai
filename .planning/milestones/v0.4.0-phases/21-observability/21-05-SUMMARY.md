---
phase: 21-observability
plan: 05
subsystem: ui
tags: [vue, pinia, typescript, vitest, workflow, executions, trigger-type, execution-status]

# Dependency graph
requires:
  - phase: 21-observability (21-02)
    provides: 后端 ExecutionStatus 枚举（含 suspended/timeout）与执行列表数据契约
provides:
  - 前端工作流 trigger_type 联合类型移除 'schedule'（TRIG-02 fail-safe）
  - executions 列表 statusOptions 与后端 ExecutionStatus 全集对齐（含 suspended/timeout）
  - executions 列表 stats execution 级"等待"判 suspended、node 级 waiting_approval 经 some() 旁路
affects: [observability, executions-ui, workflow-editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "前端枚举与后端 TextChoices 单向对齐：UI 移除不生效选项即移除误配入口（fail-safe）"
    - "execution 级 vs node 级状态语义区分：execution 永不为 waiting_approval，node 级经 node_executions.some() 旁路"

key-files:
  created: []
  modified:
    - web/src/stores/useWorkflowsStore.ts
    - web/src/pages/executions/index.vue
    - web/src/components/execution/ExecutionCard.vue
    - web/src/components/execution/ExecutionHistoryCard.vue
    - web/src/components/__tests__/executions-datatable.test.ts
    - web/src/components/__tests__/logs-datatable.test.ts

key-decisions:
  - "schedule 测试夹具改用 event 而非删除整行，保留夹具多样性与搜索用例有效性"
  - "stats waitingApproval 改判 e.status === 'suspended'，移除恒为 false 的 e.status === 'waiting_approval'"

patterns-established:
  - "TRIG-02 fail-safe：移除前端 schedule 触发类型选项/标签/类型，用户无法再配出不生效触发器"
  - "OBS-03 状态对齐：statusOptions 以 server/workflows/models/execution.py ExecutionStatus 为 SSOT"

requirements-completed: [TRIG-02, OBS-03]

# Metrics
duration: 6min
completed: 2026-06-13
---

# Phase 21 Plan 05: TRIG-02 前端清除 schedule + OBS-03 列表/卡片状态对齐 Summary

**前端移除所有工作流 schedule 假触发类型残留（联合类型/标签/图标 + 夹具），并将 executions 列表 statusOptions 与后端 ExecutionStatus 对齐（补 suspended/timeout）、stats 等待态按 execution 级 suspended + node 级 waiting_approval 区分**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-13T15:41:00Z
- **Completed:** 2026-06-13T15:47:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- TRIG-02：`useWorkflowsStore` `trigger_type` 联合类型删除 `'schedule'`，`ExecutionCard`/`ExecutionHistoryCard`/`executions/index.vue` 标签与图标映射移除 schedule 条目；仓库索引 `repositories.ts` 的 `'scheduled'` 保持不动。
- OBS-03：`executions/index.vue` `statusOptions` 补 `suspended`（挂起中）/`timeout`（超时），与后端 `ExecutionStatus` 全集对齐。
- OBS-03 / Pitfall 7：stats 的"待审批"统计改为 execution 级判 `suspended`，node 级 `waiting_approval` 经 `node_executions.some()` 旁路保留（execution 级永不为 `waiting_approval`）。
- 两个 datatable 测试夹具引用 schedule 的行改用 `event`，保持测试有效。

## Task Commits

Each task was committed atomically:

1. **Task 1: TRIG-02 — 移除前端 schedule 触发类型残留 + 更新夹具** - `c7ba7291c` (fix)
2. **Task 2: TRIG-02 + OBS-03 — executions/index.vue schedule 标签移除 + statusOptions/stats 对齐** - `0104f5340` (fix)

## Files Created/Modified
- `web/src/stores/useWorkflowsStore.ts` - `Workflow.trigger_type` 联合类型移除 `'schedule'`
- `web/src/pages/executions/index.vue` - 移除 schedule 标签/图标；statusOptions 补 suspended/timeout；stats 等待态纠偏
- `web/src/components/execution/ExecutionCard.vue` - triggerTypeLabel 移除 schedule 条目
- `web/src/components/execution/ExecutionHistoryCard.vue` - triggerTypeLabel 移除 schedule 条目
- `web/src/components/__tests__/executions-datatable.test.ts` - 夹具/标签映射/断言移除 schedule
- `web/src/components/__tests__/logs-datatable.test.ts` - 夹具 event_type schedule → event

## Decisions Made
- schedule 夹具行改用 `event` 而非整行删除：保持 datatable 行数与搜索用例（按 work_item_name `定时同步` 过滤）继续有效。
- stats `waitingApproval` 过滤条件移除恒为 false 的 `e.status === 'waiting_approval'`，改判 `e.status === 'suspended'`，node 级 `some()` 旁路保留——避免 execution/node 语义混淆。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- 全量 `vitest`（`test:unit -- <file> --run` 中 `--` 未生效为路径过滤）会跑全套用例，暴露 9 个失败：均位于本计划范围外的兄弟计划文件（`config/__tests__/status.spec.ts`、`stores/__tests__/useExecutionsStore.spec.ts`、`pages/executions/composables/__tests__/useExecutionState.spec.ts`、`components/execution/__tests__/NodeOverviewTab.spec.ts`，对应 OBS-01/OBS-02/OBS-03 卡片侧的 RED 测试）。改用正确路径过滤后，本计划的 `executions-datatable.test.ts` / `logs-datatable.test.ts`（11 passed）与 `executions/__tests__/index.spec.ts`（1 passed）全绿。
- `type-check` 报 1 处错误，位于 `components/execution/__tests__/NodeOverviewTab.spec.ts`（兄弟计划 RED 测试），非本计划改动文件；本计划修改的 `index.vue` 无新增类型错误。

## Deferred Issues
本计划范围外（SCOPE BOUNDARY，属其它计划的 RED 测试，未修复）：
- `config/__tests__/status.spec.ts`：execution `suspended` 缺中文 badge（待 status 配置侧实现）
- `stores/__tests__/useExecutionsStore.spec.ts`：`stats.suspended` / node error_message（卡片/详情侧 store）
- `pages/executions/composables/__tests__/useExecutionState.spec.ts`：OBS-02 WS 断线降级轮询
- `components/execution/__tests__/NodeOverviewTab.spec.ts`：OBS-01 结构化错误展示（含 type-check 报错）

## Next Phase Readiness
- TRIG-02 前端清理完成，UI 无 schedule 假触发入口；列表 statusOptions 与后端枚举对齐。
- 兄弟计划（OBS-01/OBS-02/OBS-03 卡片与 status 配置侧）尚有 RED 测试待实现，与本计划正交。

## Self-Check: PASSED

- `21-05-SUMMARY.md` 存在
- 提交 `c7ba7291c`、`0104f5340` 均存在于 git

---
*Phase: 21-observability*
*Completed: 2026-06-13*
