---
phase: 56-compat-progress-trace
plan: 02
subsystem: api
tags: [openai-compat, sse, reasoning_content, progress, trace, rag, retrieval, inv-5]

# Dependency graph
requires:
  - phase: 56-01
    provides: progress.py 纯函数机制层（make_reasoning_chunk / 工具名映射）+ translate_stream reasoning_content 透出范式
  - phase: 既有 compat
    provides: prepare_messages RAG 注入 + LayeredSearchService thin wrapper + ChatCompletionsView 流式/非流式分支
provides:
  - "retrieval_to_progress(result)->list[str] 纯函数：RAG 命中计数→progress 文本（非敏感，命中产 2 条/未命中空）"
  - "request_handler _prepare 内核 + prepare_messages_with_meta（暴露检索结果给流式路径），prepare_messages 委托保留旧签名"
  - "translate_stream prelude_texts 参数：role chunk 后、正文前以 reasoning_content 透出检索 progress（空则逐字等价）"
  - "views 流式分支接线 prepare_messages_with_meta + retrieval_to_progress→prelude_texts，兑现 TRACE-01 可见效果"
  - "view 级端到端集成测 + 非流式 content 零回归 + 无命中 byte-eq + sentinel 全流守护"
affects: [phase-57-anthropic-messages]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "b2 元数据驱动：检索（流前同步、不发 AgentEvent）的可见 progress 由 view 据非敏感计数元数据合成，而非事件映射（DEVIATION D-1 兑现）"
    - "prelude_texts 注入点：role chunk 后、runner 正文流前，复用 Plan 01 make_reasoning_chunk，与 THINKING/TOOL_USE progress 同源"
    - "_prepare 内核 + 双公开签名（旧 prepare_messages 委托 / 新 with_meta 暴露元数据），单次检索两路径复用、非流式不二次检索"

key-files:
  created: []
  modified:
    - server/compat/progress.py
    - server/compat/request_handler.py
    - server/compat/adapter.py
    - server/compat/views.py
    - server/tests/compat/test_progress.py
    - server/tests/compat/test_adapter.py
    - server/tests/compat/test_chat_completions.py

key-decisions:
  - "retrieval_to_progress 只读 final_context 真值（判空）+ layers.result_count/repository_ids 计数标量；绝不内联 final_context 文本/query/items/score（INV-5）"
  - "N 计数：layers 非空取 sum(result_count)，layers 空回退 len(repository_ids)，max(N,0) 保非负 int"
  - "view post 统一 prepare_messages_with_meta 单次检索；流式派生 prelude、非流式忽略 retr（content 零回归、不二次检索）"
  - "prelude 首条文案用 '正在检索 RAG…'（带省略号，区别 Plan 01 工具映射 '正在检索 RAG'），第二条 '检索完成，命中 N 处'"
  - "既有 2 个 view 测试 patch target 从 prepare_messages 迁到 prepare_messages_with_meta（返回 tuple），随 view 重构必然调整"

patterns-established:
  - "元数据驱动 prelude：流前同步检索经 view 合成可见 progress（Option B/b2），不伪造 AgentEvent"
  - "零回归三守护：无命中 byte-eq + 非流式 content 逐字不变 + prelude None/[] 与现状结构等价"

requirements-completed: [TRACE-01]

# Metrics
duration: 13 min
completed: 2026-06-17
---

# Phase 56 Plan 02: compat 真实 RAG 检索 progress 透出 Summary

**流式 `/v1/chat/completions` 命中 RAG 时正文前以 `delta.reasoning_content` 可见"正在检索 RAG…"+"检索完成，命中 N 处"——经 view 层从非敏感命中计数元数据合成 prelude（Option B/b2），兑现 TRACE-01 可见效果，严守 INV-5 与零回归**

## Performance

- **Duration:** 13 min
- **Started:** 2026-06-17T11:02:00Z
- **Completed:** 2026-06-17T11:15:24Z
- **Tasks:** 3
- **Files modified:** 7（4 production + 3 test）

## Accomplishments
- `progress.py` 新增 `retrieval_to_progress(result) -> list[str]`：命中（final_context 非空）派生 `["正在检索 RAG…", "检索完成，命中 N 处"]`，未命中/None 返回 `[]`；N 取 `sum(layers.result_count)`、layers 空回退 `len(repository_ids)`。只读非敏感计数标量，绝不内联 final_context/query/items（INV-5）。
- `request_handler.py` 抽 `_prepare` 内核返回 `(lc_messages, 检索结果|None)`；`prepare_messages` 委托并仅返回 lc_messages（旧签名/字节级行为不变，4 个既有测试不回退）；新增 `prepare_messages_with_meta` 暴露检索元数据给流式路径。
- `adapter.py` `translate_stream` 新增 `prelude_texts` 参数：role=assistant 首 chunk 之后、runner 正文流之前逐条 `make_reasoning_chunk` 透出；None/空时不产任何 chunk（与 Plan 01 逐字等价）。
- `views.py` 流式分支经 `prepare_messages_with_meta` + `retrieval_to_progress` 派生 `prelude_texts` 透传 `_stream_chunks`→`translate_stream`；非流式忽略 `retr`（不合成、`message.content` 零回归、不二次检索）。
- 守护测试全部落地：retrieval_to_progress 单测 + sentinel（6 例）；translate_stream prelude 直测 + **view 级 `ChatCompletionsView.post(stream=True)` 端到端**（正文前两条有序 reasoning_content + 全流无 tool_calls）+ 非流式 content 逐字不变 + 无命中 byte-eq + include_usage 一致 + sentinel 全流（6 例）。`tests/compat/` 43 → 55 passed。

## Task Commits

每个任务原子提交：

1. **Task 1: progress.py 增 retrieval_to_progress 纯函数 + 单测** - `481cf8fa7` (feat)
2. **Task 2: _prepare/prepare_messages_with_meta + translate_stream prelude_texts + view 流式接线** - `13e28fd26` (feat)
3. **Task 3: 流式检索 progress 集成 + 非流式零回归 + byte-eq + sentinel 测** - `0b14e7e60` (test)

**Plan metadata:** （本提交）docs(56-02)

## Files Created/Modified
- `server/compat/progress.py` (修改) - 新增 `retrieval_to_progress`（命中计数派生 progress，非敏感）+ `__all__` 更新。
- `server/compat/request_handler.py` (修改) - 抽 `_prepare` 内核返回 tuple；`prepare_messages` 委托保留旧签名；新增 `prepare_messages_with_meta`。
- `server/compat/adapter.py` (修改) - `translate_stream` 新增 `prelude_texts` 参数（role chunk 后、正文前透出检索 progress）。
- `server/compat/views.py` (修改) - 流式分支接线 `prepare_messages_with_meta` + `retrieval_to_progress`→`prelude_texts`；`_stream_chunks` 增 `prelude_texts` 形参；非流式忽略 retr。
- `server/tests/compat/test_progress.py` (修改) - retrieval_to_progress 命中/未命中/求和/回退/sentinel 6 用例。
- `server/tests/compat/test_adapter.py` (修改) - prelude 有序直测 + view 端到端 + 非流式零回归 + byte-eq + include_usage + sentinel 全流。
- `server/tests/compat/test_chat_completions.py` (修改) - 2 个既有 view 测试 patch target 迁 `prepare_messages`→`prepare_messages_with_meta`（返回 tuple）。

## Decisions Made
- **b2 元数据驱动（承接 DEVIATION D-1）**：检索在 `prepare_messages` 内、流前同步发生、不发 AgentEvent（F-2），故由 view 据非敏感计数元数据合成 prelude progress，而非事件映射——本 Plan 兑现 Plan 01 预留的 TRACE-01 可见效果（Option C 的 B 部分）。
- **N 计数口径**：layers 非空取 `sum(result_count)`，layers 空回退 `len(repository_ids)`，`max(N,0)` 保非负 int；只取标量，绝不读 final_context 文本内容。
- **单次检索两路径复用**：view post 统一 `prepare_messages_with_meta`，避免非流式二次检索；非流式忽略 `retr` 保 `message.content` 零回归。
- **prelude 文案**：首条 `"正在检索 RAG…"`（带省略号，刻意区别 Plan 01 工具映射的 `"正在检索 RAG"`），第二条 `"检索完成，命中 N 处"`。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 必要测试调整] 既有 view 测试 patch target 迁移**
- **Found during:** Task 2（views.post 改用 `prepare_messages_with_meta`）
- **Issue:** `test_chat_completions.py` 的 `test_chat_completions_stream_format` / `test_non_streaming_response` 原 patch `compat.views.prepare_messages`；view 重构后该函数不再被 post 调用，patch 失效会落到真实检索路径。
- **Fix:** 两测 patch target 迁 `compat.views.prepare_messages_with_meta`，返回值由 `[HumanMessage]` 改为 `([HumanMessage], None)` tuple。
- **Files modified:** server/tests/compat/test_chat_completions.py
- **Verification:** `uv run pytest tests/compat/ -q` → 55 passed。
- **Committed in:** `13e28fd26`（Task 2 commit）

---

**Total deviations:** 1 auto-fixed（1 Rule 1 必要测试调整）。
**Impact on plan:** 仅为 view 重构的必然连带调整（plan Task 2 已预告 view 改调 with_meta），无语义变化、无 scope creep。

## Issues Encountered
None - 计划按写就执行；plan-level 验证（ruff compat/ 全绿、grep `tool_calls` 仅类型注解/注释无写入）全部通过。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- TRACE-01 可见效果交付：流式命中 RAG 时正文前可见两条检索 progress；与 Plan 01 机制层（工具事件映射）共同覆盖 RESEARCH 推荐的 Option C（A 机制 + B 效果）。
- Phase 57（Anthropic `/v1/messages`）可复用同一抽象：`make_reasoning_chunk`/`tool_event_to_progress`/`retrieval_to_progress` 纯函数 + prelude 注入范式（Anthropic 侧映射为 thinking block）。

---
*Phase: 56-compat-progress-trace*
*Completed: 2026-06-17*

## Self-Check: PASSED

- key-files.modified 均存在于磁盘（progress.py/request_handler.py/adapter.py/views.py + 3 test 文件）。
- `git log --grep="56-02"` 返回 3 个任务提交（481cf8fa7 / 13e28fd26 / 0b14e7e60）。
- 全部 `<acceptance_criteria>` 复核通过：
  - Task 1：`progress.py` 含 `def retrieval_to_progress`，函数体仅 `getattr(result,"final_context",None)` 判空 + 读 `layers.result_count`/`repository_ids` 计数标量，不引 query/items 文本；命中产 2 条、未命中空、sentinel 不出现。
  - Task 2：`request_handler.py` 含 `def _prepare` 与 `def prepare_messages_with_meta` 且 `prepare_messages` 委托；`adapter.py translate_stream` 签名含 `prelude_texts`；`views.py` 流式分支调 `prepare_messages_with_meta` + `retrieval_to_progress`。
  - Task 3：prelude None/[] 与现状结构 byte-eq；命中时正文前两条有序 reasoning_content（translate_stream 直测 + view 端到端）；全流无 tool_calls；非流式 content 逐字不变且无检索 progress；sentinel 全流不泄漏。
- plan-level `<verification>`：`uv run pytest tests/compat/ -q` → 55 passed；`uv run ruff check compat/` → All checks passed；grep `tool_calls` 在 compat/ 仅命中 Literal 类型注解与注释（无写入 delta.tool_calls / finish_reason=tool_calls）。
