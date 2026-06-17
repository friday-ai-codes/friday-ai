---
phase: 57-anthropic-messages
plan: 02
subsystem: api
tags: [anthropic, messages, compat, sse, streaming, thinking-block, trace, drf]

requires:
  - phase: 57-01
    provides: anthropic_adapter（SSE 双行帧 helper + 8 事件骨架纯函数 + translate_stream text/收尾路径 + aggregate_message）、MessagesView 非流式骨架、AnthropicMessagesRequestSerializer
  - phase: 56-compat-trace
    provides: progress 纯函数（retrieval_to_progress / tool_event_to_progress）+ prepare_messages_with_meta 单次检索元数据通道
provides:
  - "POST /v1/messages 流式 SSE（message_start → [thinking block] → text block → message_delta → message_stop），event:+data: 双行帧、不发 [DONE]"
  - "translate_stream prelude_texts 参数：命中 RAG 时 thinking content block（index 0）承载命中计数 trace，正文 text block 顺延"
  - "translate_stream TOOL_USE_START/RESULT 前向兼容分支（复用 tool_event_to_progress，DEVIATION D-1 纯预埋）"
  - "MessagesView 流式接线（_stream_anthropic + prepare_messages_with_meta 单次检索派生 prelude）"
affects: [anthropic, compat, 58-feishu-cardkit]

tech-stack:
  added: []
  patterns:
    - "thinking block prelude 与 OpenAI reasoning_content prelude 同源（retrieval_to_progress 命中计数），物理隔离的 Anthropic 双行帧"
    - "index 单线性计数器（thinking 0 / text 紧随）；无 prelude 路径与 Plan 01 byte-eq 零回归"
    - "流式异常 → anthropic_error_event（不泄漏 traceback、不发 message_stop）"

key-files:
  created: []
  modified:
    - server/compat/anthropic_adapter.py
    - server/compat/views.py
    - server/tests/compat/test_anthropic_adapter.py
    - server/tests/compat/test_messages.py

key-decisions:
  - "可见 trace 由 prelude_texts（retrieval_to_progress 命中计数）兑现；TOOL_USE_* 分支为前向兼容纯预埋（DEVIATION D-1：compat 无 tools 永不触发）"
  - "TOOL_USE 预埋分支仅在 thinking block 已开（有 prelude）时发 thinking_delta，否则 continue——边界由 D-1 保证运行时永不命中，代码注释标明"
  - "非流式分支共用同一次 prepare_messages_with_meta 的 lc_messages、忽略 retr（content 零回归命门）"

patterns-established:
  - "Anthropic thinking block trace：prelude_texts 非空→thinking block(index 0) 先于正文；空→无 thinking block 序列仍合法（优雅降级 P-7）"
  - "安全 sentinel 全流断言：final_context/query/CoT 原文绝不外透，仅命中计数语义（INV-5/TRACE-02）"

requirements-completed: [ANTHROPIC-02]

duration: 8 min
completed: 2026-06-17
---

# Phase 57 Plan 02: Anthropic `/v1/messages` 流式 trace Summary

**POST /v1/messages 流式 SSE 接线：命中 RAG 时以 thinking content block（命中计数 trace）先于正文 text block 透出，复用 Phase 56 retrieval_to_progress，严守 INV-5/TRACE-02 与零回归**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-17T11:52:00Z
- **Completed:** 2026-06-17T12:00:00Z
- **Tasks:** 2
- **Files modified:** 4（全部修改，0 新建）

## Accomplishments
- `translate_stream` 新增 `prelude_texts: list[str] | None = None`：命中 RAG 时在正文 text block 之前发 Anthropic `thinking` content block（`content_block_start(thinking,0)` → 每条 `thinking_delta` → `content_block_stop(0)`），正文 text block index 顺延为 1；prelude 为 None/空时不发 thinking block、text block 占 index 0，与 Plan 01 路径逐字等价（byte-eq 零回归）。
- 新增 `TOOL_USE_START/TOOL_USE_RESULT` 前向兼容分支（复用 `progress.py` 的 `tool_event_to_progress`，**不改 progress.py**）：命中且 thinking block 已开时追加 `thinking_delta`，否则 continue——DEVIATION D-1 下 compat 无 tools，运行时永不触发，纯预埋，代码注释标明边界。
- `MessagesView.post` 流式接线：统一经 `prepare_messages_with_meta` 单次检索取 `(lc_messages, retr)`，流式分支 `prelude_texts = retrieval_to_progress(retr)` → `StreamingHttpResponse(content_type="text/event-stream")` 经 `_stream_anthropic` 包 `translate_stream(prelude_texts=...)`；非流式分支保持 `aggregate_message`（retr 忽略、content 零污染）。
- `_stream_anthropic` 流式异常 → `logger.exception` + `anthropic_sse_encode("error", anthropic_error_event("内部错误"))`（不泄漏 traceback、不发 message_stop），Anthropic 流不发 `[DONE]` 以 `message_stop` 收尾。
- INV-5/TRACE-02 守护：THINKING 事件静默 continue（绝不映射 thinking_delta）；绝不发 tool_use content block；安全 sentinel（SENTINEL_CTX/Q/COT）全流不外透，仅透出"命中 N 处"计数语义。
- 零回归：`tests/compat/` 全套 **109 passed**（94 baseline + adapter 新增 10 + messages 新增 5）；OpenAI 端点逐字不变、`progress.py` git diff 为空。

## Task Commits

Each task was committed atomically:

1. **Task 1: translate_stream prelude thinking block + TOOL_USE_* 前向兼容分支 + adapter 测** - `a9fc2ab75` (feat)
2. **Task 2: MessagesView 流式接线（_stream_anthropic + 单次检索派生 prelude）+ view 级集成测** - `e048efa2d` (feat)

## Files Created/Modified
- `server/compat/anthropic_adapter.py` - `translate_stream` 加 `prelude_texts`（thinking block trace）+ index 单线性计数 + `TOOL_USE_*` 前向兼容分支（import `tool_event_to_progress` / `TOOL_USE_START` / `TOOL_USE_RESULT`）
- `server/compat/views.py` - `MessagesView` 流式分支 `StreamingHttpResponse` + `_stream_anthropic`，`prelude_texts = retrieval_to_progress(retr)`
- `server/tests/compat/test_anthropic_adapter.py` - thinking prelude 集成（顺序/index）+ 无 prelude 降级 + None/[]/省略 byte-eq + 不发 tool_use + TOOL_USE 前向兼容命中/未知 noop + THINKING 不外透 + 含 prelude stop_reason（10 新增）
- `server/tests/compat/test_messages.py` - 流式 thinking 先于 text + 未命中降级 + 安全 sentinel + 非流式 content 零回归 + 流式 error 不泄漏 traceback（5 新增）

## Decisions Made
- **可见 trace 走 prelude_texts（非 TOOL_USE）**：兑现 DEVIATION D-1——compat `_build_runner` 不绑定 tools，`TOOL_USE_*` 永不发射，故可见 trace 由 `retrieval_to_progress` 命中计数经 view 层 prelude 注入兑现（与 Phase 56 OpenAI prelude 同源）。
- **TOOL_USE 预埋分支仅在 thinking block 已开时 emit**：照 plan behavior 字面实现，命中且 `thinking_index is not None` 才发 thinking_delta；该分支运行时永不命中（D-1），代码注释标明边界（N-4）。
- **index 单线性计数器**：`next_index=0`，有 prelude→thinking 占 0、text 占 1；无 prelude→text 占 0；开 text block 前已 stop thinking block（D-2/P-6）。

## Deviations from Plan

None - plan executed exactly as written.

（环境注：`uv run ruff` 在仓库根目录无 `.venv` 时无法 spawn，须在 `server/` 目录运行；不影响产物，lint 全绿。）

## Issues Encountered
None - 计划顺利执行，2 task 一次性全绿。

## User Setup Required
None - 无外部服务配置。

## Next Phase Readiness
- ANTHROPIC-01（请求映射 + 非流式）+ ANTHROPIC-02（流式 SSE + thinking block trace）均已兑现，Phase 57 完成（2/2 plans）。
- `POST /v1/messages` 流式产合法 Anthropic SSE 序列，命中 RAG 时 thinking block trace 先于正文；INV-5/TRACE-02/零回归全数成立。
- Ready for Phase 58（飞书原生流式卡片 CardKit）——与 Agent API 解耦，依赖既有飞书机器人对话路径。

---
*Phase: 57-anthropic-messages*
*Completed: 2026-06-17*
