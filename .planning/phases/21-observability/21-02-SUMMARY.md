---
phase: 21-observability
plan: 02
subsystem: testing
tags: [vitest, vue3, pinia, tdd-red, observability, websocket-fallback, status-badge]

# Dependency graph
requires:
  - phase: 21-observability (21-RESEARCH / 21-PATTERNS / 21-CONTEXT)
    provides: OBS-01/02/03 前端目标契约（node_failed 写 error、WS 降级轮询、状态枚举全覆盖 + stats 语义）与行号锚点
provides:
  - "4 个 RED vitest spec，锁死 OBS-01/02/03 前端契约（Nyquist <automated> 锚点）"
  - "ExecutionStatus 全集遍历断言（getStatusConfig 非 fallback）"
  - "node_failed WS 消息写 error_message/error_code 契约 + 缺字段防御契约（T-21-02-01）"
  - "WS CLOSED→启动轮询 / 重连→停止 / 回调用 fetchExecution 权威值契约（D-05）"
  - "结构化变量错误 parse 展示 + error_code 行契约（OBS-01）"
affects: [21-05, 21-06, 21-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "受控 @vueuse/core useWebSocket mock：暴露 data ref，写入 JSON 触发 store 内部 watch → 测试未导出的 handleWebSocketMessage"
    - "composable 测试：vi.hoisted 间谍 + mock usePolling/useExecutionsStore + storeToRefs identity + 宿主组件 mount 驱动 watch/生命周期"

key-files:
  created:
    - web/src/config/__tests__/status.spec.ts
    - web/src/stores/__tests__/useExecutionsStore.spec.ts
    - web/src/pages/executions/composables/__tests__/useExecutionState.spec.ts
    - web/src/components/execution/__tests__/NodeOverviewTab.spec.ts
  modified: []

key-decisions:
  - "stats 契约采用 execution 级 `suspended` 计数字段断言（stats.suspended===1），由 21-06 实现命名落地"
  - "结构化错误 RED 以 `not.toContain('{\"reference\"')` 断言原始 JSON 不应原样堆在错误块，避免锁死具体 DOM 结构"
  - "store 未导出 handleWebSocketMessage，改走受控 wsData ref 触发内部 watch，测试真实 WS 消费链路而非内部函数"
  - "断言用 `as any` 访问尚未实现的 stats 字段，保证 vitest 可 collect（type-check 不阻断 RED 收集）"

patterns-established:
  - "TDD RED：先行失败测试编码目标契约，提交为 test()，由后续实现计划转 GREEN"
  - "防御性/fallback 用例为 GREEN（unknown 状态 fallback、缺 error 字段防御、非 JSON 纯文本回退）"

requirements-completed: []  # RED 阶段不标记需求完成；OBS-01/02/03 由 21-05/06/07 实现后完成

# Metrics
duration: 12min
completed: 2026-06-13
---

# Phase 21 Plan 02: 前端测试脚手架 RED Summary

**4 个 RED vitest spec 锁死 OBS-01/02/03 前端契约：ExecutionStatus 全覆盖 badge、node_failed 写 error 字段 + stats suspended 语义、WS 断线降级轮询、结构化变量错误 parse + error_code 行**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-13
- **Tasks:** 3
- **Files created:** 4

## Accomplishments
- `status.spec.ts`：遍历后端 ExecutionStatus 全集（pending/running/paused/suspended/completed/failed/cancelled/timeout）断言 `getStatusConfig('execution')` 非 fallback；suspended 专项 RED；unknown fallback 保护 GREEN。
- `useExecutionsStore.spec.ts`：node_failed 应写 error_message/error_code 到对应 NodeExecution（RED）；缺字段消息防御不破坏 store（GREEN，T-21-02-01）；stats 以 execution 级 suspended 计数（RED）。
- `useExecutionState.spec.ts`：WS CLOSED + 活跃执行启动轮询、重连停止、轮询回调用 `store.fetchExecution`（服务端权威值，D-05）— 全 RED。
- `NodeOverviewTab.spec.ts`：结构化变量错误 parse 展示（RED）、error_code 行（RED）、非 JSON 纯文本回退（GREEN）。

## RED 用例清单与转绿计划

| Spec | 用例 | 当前 | 转绿计划 |
|------|------|------|----------|
| status.spec.ts | test_every_execution_status_has_non_fallback_badge | RED（suspended 命中 fallback） | 21-07 |
| status.spec.ts | test_suspended_badge_present | RED（status.ts 缺 suspended） | 21-07 |
| status.spec.ts | test_unknown_status_falls_back | GREEN（fallback 保护） | — |
| useExecutionsStore.spec.ts | test_node_failed_writes_error_message | RED（当前仅 failed_nodes++） | 21-06 |
| useExecutionsStore.spec.ts | test_node_failed_without_error_fields_is_safe | GREEN（防御契约） | — |
| useExecutionsStore.spec.ts | test_stats_execution_waiting_uses_suspended | RED（无 stats.suspended） | 21-06 |
| useExecutionState.spec.ts | test_ws_closed_starts_polling | RED（无降级轮询） | 21-05 |
| useExecutionState.spec.ts | test_ws_reconnect_stops_polling | RED（无降级轮询） | 21-05 |
| useExecutionState.spec.ts | test_polling_uses_fetch_execution | RED（未集成 usePolling） | 21-05 |
| NodeOverviewTab.spec.ts | test_structured_error_parsed | RED（直渲整段 message） | 21-07 |
| NodeOverviewTab.spec.ts | test_plain_error_fallback | GREEN（纯文本展示） | — |
| NodeOverviewTab.spec.ts | test_error_code_rendered | RED（未渲染 error_code） | 21-07 |

**汇总：** 8 RED（目标契约，实现前预期失败）+ 4 GREEN（fallback/防御契约）。所有 RED 均为**断言失败**，非 import/collect 错误（符合 verification 要求）。

## Task Commits

1. **Task 1: status.spec.ts（OBS-03 全覆盖）** - `4c341afa5` (test)
2. **Task 2: useExecutionsStore.spec.ts（OBS-01 node_failed + OBS-03 stats）** - `9b64f05cd` (test)
3. **Task 3: useExecutionState.spec.ts + NodeOverviewTab.spec.ts（OBS-02/01）** - `cdee3f1b8` (test)

## Files Created/Modified
- `web/src/config/__tests__/status.spec.ts` - ExecutionStatus 全集 badge 覆盖 RED 测试。
- `web/src/stores/__tests__/useExecutionsStore.spec.ts` - node_failed 写 error 字段 + stats suspended 语义 + 缺字段防御。
- `web/src/pages/executions/composables/__tests__/useExecutionState.spec.ts` - WS 断线降级轮询状态机 RED 测试。
- `web/src/components/execution/__tests__/NodeOverviewTab.spec.ts` - 结构化变量错误 parse/回退/error_code RED 测试。

## Decisions Made
- 见 frontmatter `key-decisions`。核心：受控 `wsData` ref 触发 store 内部 watch（绕过未导出的 handler）；composable 用宿主组件 mount + mock usePolling/store/storeToRefs 驱动 watch；RED 断言用 `as any` 规避尚未实现符号的 type-check 阻断。

## Deviations from Plan

None - plan executed exactly as written（RED 测试按契约编写，未实现源码转绿，符合 TDD RED 阶段意图）。

## Issues Encountered
- Task 3 初稿 `useExecutionState.spec.ts` 的动态 import 路径误写为 `../../useExecutionState`（spec 位于 `composables/__tests__/`，正确为 `../useExecutionState`），导致 vite 解析失败（collect error 而非断言失败）。已修正为 `../useExecutionState`，复跑后 3 用例正常 collect 并 RED 断言失败。提交前已修复，未进入历史。
- type-check（vue-tsc 全工程）未单独运行；spec 通过 `as any` 访问尚未实现的 stats 字段，未引用尚未存在的导出符号，故 vitest collect 不受影响。若后续 type-check 因实现阶段新增符号变动报错，由 21-05/06/07 实现时一并处理。

## Next Phase Readiness
- OBS-01/02/03 前端实现计划（21-05 WS 降级轮询、21-06 store node_failed + stats、21-07 status 枚举 + NodeOverviewTab）已具备 `<automated>` RED 锚点，实现完成即可逐项转绿验证。
- 无外部服务配置需求；零新增依赖（T-21-02-SC accept）。

## Self-Check: PASSED

- 4 个 spec 文件 + SUMMARY.md 均存在于磁盘。
- Task 1/2/3 提交对象（`4c341afa5` / `9b64f05cd` / `cdee3f1b8`）均存在于 git。
- 各 spec 经 vitest 收集运行：RED 用例为断言失败（非 import/collect 错误），fallback/防御用例 GREEN。

---
*Phase: 21-observability*
*Completed: 2026-06-13*
