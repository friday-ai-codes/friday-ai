---
phase: 20-validation
plan: 04
subsystem: web
tags: [workflow, validation, pinia, store, vue, frontend, issues-panel]

# Dependency graph
requires:
  - phase: 20-validation
    provides: WorkflowGraphValidator reason 枚举（20-01）
  - phase: 20-validation
    provides: bulk-update 400 结构化 {errors,warnings} + dry-run 双端点（20-02）
provides:
  - useWorkflowValidationStore 摄入后端 {errors,warnings}（severity + 多 reason，node/edge 级）
  - saveWorkflow 解析 bulk-update 400 body 灌入 validation store（错误阻断保存）
  - IssuesPanel 由 store 真实驱动渲染，按 severity 区分 error/warning（死代码消除）
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "前端校验 store 统一摄入：addIssues 把后端 snake_case（node_id/edge_id/field_path）映射为 camelCase，errors/warnings 合并入单一 issuesList，severity 派生 errorCount/warningCount"
    - "store-in-store：saveWorkflow 在 action 内 useWorkflowValidationStore() 取 store，catch ApiError(400) → addIssues(e.body)，保存前 clearAllIssues 防陈旧残留"
    - "面板视觉按 severity 分级：含 error 用 destructive 红色系，纯 warning 用 amber"

key-files:
  created:
    - web/src/stores/__tests__/useWorkflowValidationStore.test.ts
  modified:
    - web/src/stores/useWorkflowValidationStore.ts
    - web/src/stores/useWorkflowsStore.ts
    - web/src/components/workflow/validation/IssuesPanel.vue

key-decisions:
  - "采用「解析 bulk-update 400 body」而非保存前额外 dry-run：400 body 与 20-02 dry-run 同源同形态（{errors,warnings}），少一次往返且天然阻断保存"
  - "issues 与 legacy edge warnings 双轨并存：新增独立 issues 列表驱动面板；保留 warnings Map（addWarning/getWarningForEdge/syncWithEdges）向后兼容，无外部调用方破坏"
  - "warningCount 语义重定义为 warning-severity issue 计数（面板用），legacy edge warning 走 warningsList"

requirements-completed: [VAL-03]

# Metrics
duration: ~10min
completed: 2026-06-13
---

# Phase 20 Plan 04: 前端校验链路接通（store 摄入 + saveWorkflow 接线 + IssuesPanel severity 渲染）Summary

**扩展 `useWorkflowValidationStore` 摄入后端 `WorkflowGraphValidator` 的 `{errors, warnings}`（severity + 多 reason，支持 node 级与 edge 级），让 `saveWorkflow` 在 bulk-update 返回 400 时解析结构化 body 灌入 store 并阻断保存，`IssuesPanel` 改由 store 真实驱动渲染并按 severity 区分 error/warning——消除「`useWorkflowValidationStore` 无调用方、`IssuesPanel` 的 `v-if=hasWarnings` 永 false」的死代码（VAL-03）。**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-13T20:04Z
- **Completed:** 2026-06-13T20:10Z
- **Tasks:** 2
- **Files created:** 1 / **Files modified:** 3

## Accomplishments

- **useWorkflowValidationStore.ts（Task 1，TDD）**：新增 `ValidationIssue` 接口（`id/reason/severity/message/fieldPath?/nodeId?/edgeId?`）与 `BackendValidationResult` 入参类型；新增 `addIssues(payload)` 批量摄入后端 `{errors,warnings}`，把 snake_case（`node_id`/`edge_id`/`field_path`）映射为 camelCase 并生成稳定唯一 id；新增 getters `issuesList`/`errorCount`/`warningCount`/`hasIssues`/`hasErrors` 与 `getIssuesForEdge`、action `clearAllIssues`。`reason` 直接透传后端枚举（不重命名）。保留 legacy edge warning API 向后兼容。
- **useWorkflowsStore.ts（Task 2）**：`saveWorkflow` 引入 `useWorkflowValidationStore`，保存开始 `clearAllIssues()`；`catch` 分支判断 `e instanceof ApiError && e.status === 400` 且 body 含 errors/warnings → `addIssues(e.body)`，保持 `throw`（错误阻断保存，由面板呈现）。与 20-02 同源端点/字段（bulk-update 400 body 即 validator 输出）。
- **IssuesPanel.vue（Task 2）**：改用 `issuesList`/`hasIssues`/`hasErrors`/`errorCount`/`warningCount`（storeToRefs），`v-if="hasIssues"`；按 `issue.severity` 区分视觉（error → `destructive` 红 + AlertCircle，warning → amber + AlertTriangle），整体面板 tone 含 error 转红；error/warning 双 Badge 计数；node 级展示 `nodeId/fieldPath`（getNodeName 兜底），`handleIssueClick` 保留 D-06 TODO。
- **useWorkflowValidationStore.test.ts（Task 1，new）**：7 例覆盖 addIssues 混合摄入计数、snake→camel 映射、edge 级 getIssuesForEdge、唯一 id、缺省字段、clearAllIssues、legacy edge warning 向后兼容。

## Task Commits

1. **Task 1 RED: 失败单测（addIssues）** - `3c8cd0dc2` (test)
2. **Task 1 GREEN: store 扩展 + addIssues 摄入** - `5e984233c` (feat)
3. **Task 2: saveWorkflow 接 400 + IssuesPanel severity 渲染** - `f2b257279` (feat)

## Files Created/Modified

- `web/src/stores/useWorkflowValidationStore.ts` - 扩展 ValidationIssue 类型 + addIssues/clearAllIssues + severity 派生 getters；保留 legacy edge warning API
- `web/src/stores/useWorkflowsStore.ts` - saveWorkflow 接 bulk-update 400 → addIssues，错误阻断保存
- `web/src/components/workflow/validation/IssuesPanel.vue` - store 驱动真实渲染 + severity 视觉区分（死代码消除）
- `web/src/stores/__tests__/useWorkflowValidationStore.test.ts` - VAL-03 store 摄入/映射/计数单测（new）

## Decisions Made

- **解析 400 body 而非额外 dry-run：** PLAN 允许二选一。bulk-update 的 400 body 由后端同一 validator 产出，形态与 20-02 dry-run 完全一致（`{errors,warnings}`），直接解析少一次网络往返，且 400 天然阻断保存——无需前置 dry-run 拦截逻辑。
- **issues / legacy warnings 双轨：** 新增独立 `issues` 列表驱动面板，`warnings` Map 仅服务边视觉 schema_mismatch。grep 确认 legacy API 仅 IssuesPanel + store 自身引用，重写面板后无外部破坏；按 PLAN 要求保留以防潜在调用方。
- **warningCount 语义：** 重定义为 warning-severity issue 计数（面板用），legacy edge warning 改走 `warningsList`，避免新旧计数耦合。

## Deviations from Plan

None - plan executed exactly as written（采用 PLAN 明示的「解析 400 body」分支实现，非偏离）。

## Threat Surface

与 PLAN `<threat_model>` 对齐：
- T-20-11（IssuesPanel 渲染后端 message 信息泄露）：前端原样展示后端 `message`，不额外拼接 config 取值；后端 ValidationIssue 已只含键名/路径/reason（20-01/20-02 保证）。✅
- T-20-12（前端跳过校验直接保存）：accept——前端校验为体验增强，服务端 bulk-update 仍强制校验（20-02），前端绕过不影响落库安全。✅

无新增信任边界 / 网络端点 / 鉴权路径。

## Verification

- `pnpm exec vitest run src/stores/__tests__/useWorkflowValidationStore.test.ts` → 7 passed。
- `pnpm type-check`（vue-tsc --noEmit）→ 通过，零错误。
- `pnpm exec eslint`（四个改动文件）→ 通过（import 顺序 --fix 已修）。
- grep 守护：useWorkflowsStore.ts 命中 `useWorkflowValidationStore`/`addIssues`/`clearAllIssues`；IssuesPanel.vue 命中 `severity`/`hasIssues`，`hasWarnings` 计数为 0（死代码消除）。

## Manual verification (end-of-phase)

| Behavior | Why Manual |
|----------|------------|
| 编辑器造环/坏 handle 保存 → IssuesPanel 弹出结构化 errors 且保存被拒；修正后保存成功 | 浏览器画布交互观感，vitest 无法覆盖完整 X6 交互 |

## State Sync Note

按本次执行约束（sequential / 不改阶段级字段），未运行 STATE.md / ROADMAP.md 的 advance-plan / update-progress 等状态写入；仅交付代码、测试与本 SUMMARY。

## Self-Check: PASSED

- 创建/修改文件全部存在：useWorkflowValidationStore.ts / useWorkflowsStore.ts / IssuesPanel.vue / useWorkflowValidationStore.test.ts / 20-04-SUMMARY.md。
- 任务提交全部存在：3c8cd0dc2 / 5e984233c / f2b257279。
- 验证：store 单测 7 例绿；type-check 通过；eslint 通过；grep 守护满足。

---
*Phase: 20-validation*
*Completed: 2026-06-13*
