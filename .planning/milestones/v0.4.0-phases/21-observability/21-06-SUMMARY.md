---
phase: 21-observability
plan: 06
subsystem: web
tags: [observability, execution-status, websocket, pinia, vitest]

requires:
  - phase: 21-observability
    plan: 02
    provides: status.spec / useExecutionsStore.spec RED 测试契约
  - phase: 21-observability
    plan: 04
    provides: 后端 WS 广播 node_failed 携带 error_message/error_code 字段契约
provides:
  - "executionStatusConfig 含 suspended badge（OBS-03，与后端 ExecutionStatus 全集对齐）"
  - "useExecutionsStore.node_failed 防御性写入 NE error_message/error_code（OBS-01）"
  - "stats 区分 execution(suspended) vs node(waiting_*)，新增 stats.suspended（OBS-03）"
affects: [21-07]

tech-stack:
  added: []
  patterns:
    - "execution 级等待态用 suspended（Phase 18 落点），node 级用 waiting_*，统计/筛选不混淆"
    - "WS 广播写 store 用防御读（data.x != null 才覆盖），缺字段不破坏 NE 状态"

key-files:
  created: []
  modified:
    - web/src/config/status.ts
    - web/src/stores/useExecutionsStore.ts

key-decisions:
  - "新增 stats.suspended 仅统计 execution.status==='suspended'；waitingApproval 保留为 suspended ∪ node 级 waiting_approval 旁路"
  - "waiting_approval/waiting_input badge 保留（供 node 状态渲染），注释标注非 execution 级用途"

patterns-established:
  - "前端执行状态枚举镜像后端 ExecutionStatus SSOT"

requirements-completed: [OBS-01, OBS-03]

duration: ~8min
completed: 2026-06-13
---

# Phase 21 Plan 06: 执行状态枚举对齐 + node_failed 写 error Summary

**executionStatusConfig 补 suspended badge 与后端 ExecutionStatus 对齐；useExecutionsStore 的 node_failed WS 处理防御性写入 NE error_message/error_code；stats 区分 execution(suspended) 与 node(waiting_*) 等待态。**

> **本计划由 orchestrator inline 执行**（gsd-executor 子代理派发遇间歇性账单错误无法启动，按 execute-phase inline fallback 落地）。改动为两个前端 TS 文件、纯增量，风险可控。

## Accomplishments
- `config/status.ts`：`executionStatusConfig` 新增 `suspended: { label:'挂起中', icon:'lucide--pause-circle', variant:'warning' }`（timeout 已有保留）；`waiting_approval`/`waiting_input` 保留并注释标注仅供 node 状态渲染。
- `useExecutionsStore.ts` node_failed 分支：保留 `failed_nodes++`，新增按 `ne.node === node_id` 找 NE 并防御读写 `error_message`/`error_code`（`data.x != null` 才覆盖，Pitfall 5）。
- `useExecutionsStore.ts` stats：新增 `suspended`（仅 execution.status==='suspended'）；`waitingApproval` 改为 execution 级 suspended ∪ node 级 waiting_approval（some 旁路），移除恒 false 的 `e.status==='waiting_approval'`。

## Task Commits
1. OBS-03 status.ts suspended badge — 见提交
2. OBS-01/03 useExecutionsStore node_failed + stats — 见提交

## Verification
- `pnpm -C web test:unit src/config/__tests__/status.spec.ts src/stores/__tests__/useExecutionsStore.spec.ts` → 6 passed。
- `pnpm -C web type-check` 两改动文件无新增错误。
- 注：useExecutionState.spec / NodeOverviewTab.spec 仍 RED，属 21-07 职责（WS 降级 + 结构化错误展示）。

## Self-Check: PASSED
