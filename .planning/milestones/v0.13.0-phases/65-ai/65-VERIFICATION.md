---
phase: 65
slug: ai
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 65 — Verification（AI 对话串流隔离修复）

## Goal-Backward Verification

**Phase Goal:** 修复 AI 对话跨会话"串流"——把前端全局单例 streaming 状态与副作用改为按 `conversation_id` 隔离，切会话不串台（后台流继续但仅写回所属会话）。

## Checks

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | 会话 A 流式进行中切到 B，B 界面不出现 A 的 token/回答（实时与刷新均正确） | ✅ | `handleSSEEvent` owner 守护：owner≠current 时不写 streaming state；切回由 restoreConversationRuntime 从后端 finalize 恢复。守护测试「后台会话流事件不写入当前会话 streaming state」 |
| 2 | `useSSEStream` 流闭包绑定发起 conversation_id；模块级 currentRunId 改每流独立、不跨并发流覆盖 | ✅ | `connectSSE` 本流局部 `streamRunId` + `options.onRunId`；`sendMessage` onEvent 闭包注入 `ownerConversationId`，run_id 用局部 ref；`lastRunId` 仅兼容旧 `getCurrentRunId`（@deprecated） |
| 3 | `handleSSEEvent`/`sendMessage` finally merge / `title_generated` / `scheduleRuntimePoll` 副作用校验"事件所属会话===当前会话" | ✅ | `handleSSEEvent` owner 守护；`title_generated` 后台仅更新列表标题；`sendMessage` finally `isCurrent` 守护 merge/poll/reset/error。守护测试「title_generated 更新列表标题但不影响当前会话视图」 |
| 4 | 既有单会话流式 / stop / 刷新恢复零回归，vitest 守护"切会话不串台" | ✅ | `pnpm vitest run src/stores/__tests__/ src/composables/__tests__/` → 23 文件 170 测全绿（新增 isolation 5 例 + 既有全部零回归）；eslint clean |

## Result

**PASSED** — 4/4 success criteria 满足。后端 SSE 已按 conversation_id 隔离，本 phase 纯前端隔离 + 守护测试落地，零回归。
