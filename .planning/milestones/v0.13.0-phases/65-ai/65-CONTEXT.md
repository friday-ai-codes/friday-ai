# Phase 65: AI 对话串流隔离修复 - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — recommended answers accepted)

<domain>
## Phase Boundary

修复 AI 对话跨会话"串流"：把前端**全局单例** streaming 状态与副作用改为按 `conversation_id` 隔离。会话 A 流式输出进行中切到会话 B，B 的界面不再出现 A 的 token / 回答（实时显示与刷新后均正确）。后端 SSE 已按 `conversation_id` 隔离，本 phase 纯前端（`web/src/composables/useSSEStream.ts` + `web/src/stores/chat.ts`），复用已修复的 ClarificationCard 跨会话过滤模式（`upsertClarification(payload, conversationId)` + `ChatMessageArea` 按 `currentConversationId` 过滤）。

**不在范围内**：后端 SSE 改造（已隔离）；多会话并发流式 UI 同屏展示（仍单视图）；停止后台流（后台流继续，仅 UI 不串）。
</domain>

<decisions>
## Implementation Decisions

### Area 1: 流隔离机制
- `useSSEStream.connectSSE` 的模块级 `currentRunId` 单例改为**每流独立**：`connectSSE` 内部局部 `runId` 变量，`getCurrentRunId` 不再返回跨并发流共享的全局值；改为 `connectSSE` 返回 `{ getRunId }` 句柄或经回调透出本流 run_id，避免并发流互相覆盖。
- 流处理闭包绑定**发起时的 `conversationId`**：`onEvent` 回调在 `sendMessage` 内以闭包捕获 `conversationId`，事件分派前判定"事件所属会话 === store.currentConversationId"。
- 事件归属判定优先用事件自带字段（若后端 SSE event 带 `conversation_id`），否则用闭包捕获的发起会话 id 作为权威归属。

### Area 2: 切会话后台流行为
- 切会话**不 abort** 正在进行的后台流（保留后端继续执行、落库），仅停止把其事件写入当前 UI。
- 切回原会话时由既有 `restoreConversationRuntime` / runtime 轮询恢复在途状态（已实现路径，复用）。
- `stopStreaming`(用户显式停止) 行为不变，仍 abort 当前会话流。

### Area 3: 副作用守护范围
- `handleSSEEvent` 增加 `ownerConversationId` 入参（由 `sendMessage` 闭包注入）；当 `ownerConversationId !== currentConversationId.value` 时，**不写当前 UI 的 streaming state**（streamingParts/content/thinking/toolCalls/timeline/phase 等），数据仍由后端 finalize 落库。
- `sendMessage` 的 `finally` 合并块（merge 流式内容到 `messages`、`scheduleRuntimePoll`、waiting 早退）全部以发起会话 id 与当前会话 id 比对：仅当二者相等才写当前 `messages` / 启动当前轮询。
- `title_generated`：仅当事件归属会话 === 当前会话才更新标题 UI（否则仅更新 `conversations[]` 中对应会话条目的 title，不触当前视图渲染副作用）。
- `scheduleRuntimePoll` 仅对当前会话调度；为非当前会话调度时跳过。

### Area 4: 测试与零回归
- vitest 守护：模拟会话 A 流式进行中 `currentConversationId` 切到 B，dispatch A 的 SSE 事件，断言 B 的 streaming state 不被写入；切回 A 后状态可由 runtime 恢复。
- 既有正常单会话流式、`stopStreaming`、刷新恢复（`restoreConversationRuntime` / `applyRuntimeSnapshot`）行为零回归（既有 `chat.*.spec.ts` 全绿）。
- 复用 `_dispatchSSE` 测试入口（需扩展为可携带 owner 会话 id）。

### Claude's Discretion
- 句柄/回调透出 run_id 的具体形态（返回值对象 vs onEvent 透传），取实现最简且可测者。
- 归属判定字段优先级（事件 `conversation_id` vs 闭包捕获 id）的具体兜底顺序。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `web/src/composables/useSSEStream.ts` — `connectSSE(conversationId, ...)` 已接收 conversationId；模块级 `currentRunId` / `getCurrentRunId()` 是并发污染点。
- `web/src/stores/chat.ts` — `handleSSEEvent`（巨型 switch）、`sendMessage`（finally merge + waiting 早退 + scheduleRuntimePoll）、`title_generated` case、`scheduleRuntimePoll`、`pollConversationRuntime`、`_dispatchSSE` 测试入口。
- ClarificationCard 跨会话过滤模式：`upsertClarification(payload, conversationId)` 写入时绑定 conv 维度 + `ChatMessageArea` 按 `currentConversationId` 过滤渲染（284 round 2 hotfix，本 phase 直接对齐复用）。
- `clearAllClarifications()` 已在 `selectConversation` / `createNewConversation` 清理跨会话残留卡片。

### Established Patterns
- Pinia setup-store 风格；流式态为顶层 `ref` 单例（这正是串台根因——需以 owner 会话 id 守护写入）。
- 既有刷新恢复链路：`selectConversation → restoreConversationRuntime → applyRuntimeSnapshot`（不动，复用）。

### Integration Points
- `sendMessage` 内 `connectSSE(..., (event) => handleSSEEvent(event), ...)` 是注入 owner 会话 id 的接缝。
- 测试经 `_dispatchSSE` 直驱 `handleSSEEvent`。

</code_context>

<specifics>
## Specific Ideas

- 复刻 ClarificationCard 的"写入即绑定 conv 维度 + 渲染/写入按当前会话过滤"双保险，作为本 phase 隔离的范式。
- 后台流"继续执行但只写所属会话"是核心语义——不要为了隔离去 abort 后台流（会丢后端在途回答）。
</specifics>

<deferred>
## Deferred Ideas

- 多会话流式并发同屏展示（如侧栏"运行中"指示器实时跳动）— 超出本 phase 范围。
- 后端 SSE event 统一补 `conversation_id` 字段（若当前未带，可作为后续增强；本 phase 以闭包捕获 id 为权威）。
</deferred>
