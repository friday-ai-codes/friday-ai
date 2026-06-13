---
phase: 21-observability
plan: 07
subsystem: web
tags: [observability, execution-detail, websocket, polling, dag, vitest]

requires:
  - phase: 21-observability
    plan: 02
    provides: NodeOverviewTab.spec / useExecutionState.spec RED 契约
  - phase: 21-observability
    plan: 04
    provides: 后端 WS 广播 error_message/error_code 字段契约
  - phase: 21-observability
    plan: 06
    provides: store node_failed 写入 NE error_message/error_code（DAG tooltip 数据源）
provides:
  - "NodeOverviewTab error_code 行 + parseStructuredError 结构化错误展示/纯文本回退（OBS-01）"
  - "ExecutionNode statusBorderClass/statusDotClass 补 suspended/timeout + 失败节点 error tooltip（OBS-03/OBS-01）"
  - "useExecutionState WS 断线降级 REST 轮询（usePolling 5s，fetchExecution 权威值），重连/终态停止（OBS-02）"
affects: []

tech-stack:
  added: []
  patterns:
    - "结构化错误前端解析：末行 JSON.parse 成功→summary+detail 友好展示，失败→纯文本回退（不 eval、不递归）"
    - "WS 断线降级：watch(wsDisconnected) → usePolling start/stop，fetchExecution 全量覆盖为单一真相，不与 WS 本地推断并存"

key-files:
  created: []
  modified:
    - web/src/components/execution/NodeOverviewTab.vue
    - web/src/components/execution/dag/ExecutionNode.vue
    - web/src/pages/executions/composables/useExecutionState.ts
    - web/src/components/execution/__tests__/NodeOverviewTab.spec.ts

key-decisions:
  - "parseStructuredError 仅浅层 key-value 展示 detail（富交互留 v2）；JSON.parse try/catch 回退纯文本（T-21-07-03）"
  - "DAG suspended/timeout 为防御性补色（DAG 渲染 NodeExecution，理论无 suspended）；失败 tooltip 为最小实现"
  - "降级轮询复用 store.fetchExecution（既有对象级权限，T-21-07-02），不新增旁路"

patterns-established:
  - "执行详情页可观测：实时失败可见 + 断线降级 + 状态如实"

requirements-completed: [OBS-01, OBS-02, OBS-03]

duration: ~15min
completed: 2026-06-13
---

# Phase 21 Plan 07: 执行详情页可观测三项 Summary

**NodeOverviewTab 展示 error_code + 结构化变量错误友好解析（非 JSON 回退纯文本）；DAG ExecutionNode 补 suspended/timeout 色 + 失败节点 error tooltip；useExecutionState 在 WS 断线时降级 REST 轮询（fetchExecution 权威值），重连/终态停止。**

> **本计划由 orchestrator inline 执行**（gsd-executor 子代理派发遇间歇性账单错误无法启动，按 execute-phase inline fallback 落地）。三个前端文件、纯前端改动，风险可控。

## Accomplishments
- **OBS-01 NodeOverviewTab**：新增 `parseStructuredError(msg)`（split('\n') → 末行 JSON.parse，成功返回 {summary, detail}，失败回退 {summary: msg, detail: null}）；错误块展示 summary（pre）+ detail 浅层 key-value；信息行新增 error_code 行。
- **OBS-03/OBS-01 ExecutionNode**：`statusBorderClass`/`statusDotClass` 补 suspended（purple）/timeout（rose）防 fallback；失败节点状态点包 Tooltip 展示 `data.nodeExecution.error_message`（最小实现）。
- **OBS-02 useExecutionState**：`usePolling(() => store.fetchExecution(id), {interval:5000, immediate:true})` + `watch(wsDisconnected, d => d ? startPoll() : stopPoll())`；轮询以 fetchExecution 全量覆盖为单一真相，断线期不与 WS 本地推断并存（Pitfall 6）。

## Task Commits
1. NodeOverviewTab error_code + 结构化错误解析 — `8d7adddec`
2. ExecutionNode suspended/timeout 色 + 失败 tooltip — `0e039bcde`
3. useExecutionState WS 降级轮询 — `56e579c9c`

## Verification
- `pnpm -C web test:unit` 全量 **1017 passed / 0 failed / 1 skipped**（NodeOverviewTab.spec 3 + useExecutionState.spec 3 转绿）。
- `pnpm -C web type-check` exit 0（顺手修 21-02 RED spec 的 props 类型不匹配，cast as any）。

## Deviations
- 21-02 的 NodeOverviewTab.spec mountTab props 类型不满足 vue-tsc（Record<string,any> → NodeExecution），加 `as any` cast 使 type-check 通过（不改测试语义）。

## Self-Check: PASSED
