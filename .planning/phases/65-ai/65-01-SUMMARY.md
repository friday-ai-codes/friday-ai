---
phase: 65-ai
plan: 01
subsystem: frontend-chat
tags: [sse, streaming, conversation-isolation, pinia, vue]

requires:
  - phase: "284 (ClarificationCard hotfix)"
    provides: "写入按 conversation 维度过滤 + 渲染按 currentConversationId 过滤范式"
provides:
  - "useSSEStream 按流独立 run_id（onRunId 回调）"
  - "handleSSEEvent owner 会话守护（后台流不写当前 UI）"
  - "sendMessage finally isCurrent 守护（切走不 merge/poll/reset/error）"
affects: [chat 前端流式 UI]

tech-stack:
  added: []
  patterns:
    - "SSE 事件回写以发起会话为权威归属，handleSSEEvent(event, ownerConversationId) 前台守护"
    - "per-stream run_id 闭包局部 ref，替代模块级单例避免并发流互相覆盖"

key-files:
  created:
    - web/src/stores/__tests__/chat.stream-isolation.spec.ts
  modified:
    - web/src/composables/useSSEStream.ts
    - web/src/stores/chat.ts

status: complete
---

# Phase 65 Plan 01 Summary — AI 对话串流隔离修复

## 做了什么

修复 AI 对话跨会话"串流"：把前端全局单例 streaming 状态与副作用改为按 `conversation_id` 隔离。

- **`useSSEStream.ts`**：`connectSSE` 内引入本流局部 `streamRunId`，新增 `options.onRunId(runId)` 回调按流透出 run_id；模块级 `currentRunId` 降级为 `lastRunId` 仅兼容旧 `getCurrentRunId`（标记 `@deprecated`，不再用于并发判定）。消除并发流互相覆盖 run_id。
- **`chat.ts` `handleSSEEvent(event, ownerConversationId?)`**：入口判定 `isForeground = !owner || owner === currentConversationId`。后台流（owner ≠ current）仅放行 `title_generated` 更新所属会话在列表中的标题，其余事件一律 return，不写当前 UI 的 streaming state。未传 owner（旧调用 / `_dispatchSSE` 单测）按前台处理 —— 零回归。
- **`chat.ts` `sendMessage`**：`onEvent` 闭包注入 `ownerConversationId = conversationId`（发起会话）；断线恢复轮询与 error 写入均以 `ownerConversationId === currentConversationId` 守护；本流 run_id 改用局部 `streamRunIdRef`（替代 `getCurrentRunId`）；`finally` 以 `isCurrent` 守护所有「写当前 UI」收尾（merge 到 messages / scheduleRuntimePoll / resetStreamingState / error / 草稿失败重置），用户切走后仅做草稿会话列表提升然后 `return`。
- 后台流**不 abort**：后端继续 finalize 落库；切回发起会话时由 `selectConversation → restoreConversationRuntime → applyRuntimeSnapshot` 恢复在途内容（既有路径复用）。
- 新增 `chat.stream-isolation.spec.ts`（5 例）守护。

## 验收

- `pnpm vitest run src/stores/__tests__/ src/composables/__tests__/` → **23 文件 170 测全绿**（含新增 isolation 5 例 + 既有 runtime/edit-fork/multimodal/clarification/useSSEStream 零回归）。
- `eslint` 改动文件 clean。

## 决策

- SSE 事件不带 `conversation_id` 字段（见 `types/chat.ts`），故以 `sendMessage` 闭包捕获的发起会话 id 作为权威归属。
- 切会话不 abort 后台流（保留后端在途回答），仅 UI 不串 —— 对齐 phase boundary「后台流继续但仅写回所属会话」。
