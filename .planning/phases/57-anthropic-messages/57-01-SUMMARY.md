---
phase: 57-anthropic-messages
plan: 01
subsystem: api
tags: [anthropic, messages, compat, sse, adapter, drf, langchain]

requires:
  - phase: 56-compat-trace
    provides: compat 内核（_build_runner / prepare_messages_with_meta / OptionalBearerTokenAuth / LangChainAgentRunner.stream / progress 纯函数）
provides:
  - "POST /v1/messages（+ /v1/messages/）Anthropic Messages 兼容端点（非流式）"
  - "AnthropicMessagesRequestSerializer（max_tokens 必填、system 顶层、role user/assistant）"
  - "anthropic_to_openai_messages 形状规整纯函数（system 提顶 + block→text part，委托既有内核）"
  - "anthropic_adapter.py：SSE 双行帧编码 helper + 8 事件骨架纯函数 + stop_reason/usage 映射 + AnthropicCompatAdapter.translate_stream（text/收尾路径）+ aggregate_message 非流式聚合"
  - "anthropic_error_response Anthropic error envelope helper"
affects: [57-02-anthropic-streaming, anthropic, compat]

tech-stack:
  added: []
  patterns:
    - "Anthropic 专属 SSE 双行帧（event:+data:），与 OpenAI 单行帧 sse_encode 物理隔离"
    - "事件骨架纯函数 + index 单线性计数器，为 Plan 02 prelude/TOOL_USE 扩展预留结构"
    - "纯增量：新增符号不改既有 OpenAI 符号，progress.py 逐字不动"

key-files:
  created:
    - server/compat/anthropic_adapter.py
    - server/tests/compat/test_anthropic_schemas.py
    - server/tests/compat/test_anthropic_adapter.py
    - server/tests/compat/test_messages.py
  modified:
    - server/compat/schemas.py
    - server/compat/request_handler.py
    - server/compat/error_handlers.py
    - server/compat/views.py
    - server/compat/urls.py

key-decisions:
  - "stream=True 本 plan 暂走非流式聚合 + 显式 TODO(Plan 02)，避免半成品流式（删除 501 等替代犹豫项）"
  - "_status_to_stop_reason 恒返回 end_turn（completed/interrupted/max_iterations），预留 max_tokens 映射位（D-3）"
  - "usage 改名 input/output → input_tokens/output_tokens（_rename_usage，P-2，绝不透传原 key）"
  - "aggregate_message 与 translate_stream 同源翻译核（共用映射纯函数），content 仅 TEXT_DELTA 正文（零 trace 污染，P-8）"

patterns-established:
  - "Anthropic SSE 双行帧 anthropic_sse_encode：绝不复用 OpenAI sse_encode（无 event: 行）"
  - "INV-5/TRACE-02：THINKING/TOOL_USE 静默 continue，绝不发 tool_use content block"

requirements-completed: [ANTHROPIC-01]

duration: 5 min
completed: 2026-06-17
---

# Phase 57 Plan 01: Anthropic `/v1/messages` 地基 Summary

**POST /v1/messages 非流式 Anthropic Messages 兼容端点：请求映射（max_tokens 必填 / system 顶层）+ 双行帧 SSE adapter 骨架 + aggregate_message 聚合，复用 Phase 56 内核零回归**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-17T11:44:55Z
- **Completed:** 2026-06-17T11:50:26Z
- **Tasks:** 3
- **Files modified:** 9（4 created + 5 modified）

## Accomplishments
- `AnthropicMessagesRequestSerializer` + `anthropic_to_openai_messages` 规整纯函数：把 Anthropic 形状（system 顶层、max_tokens 必填、role user/assistant、text/image_url parts）摊平为既有 `prepare_messages_with_meta` 期望的 `[{role, content}]`，完全委托既有 RAG/检索内核。
- 新建 `anthropic_adapter.py`：`anthropic_sse_encode` 双行帧 helper（不复用 OpenAI `sse_encode`）、8 个事件骨架纯函数（含 thinking 系列，为 Plan 02 预埋）、`_status_to_stop_reason`/`_rename_usage` 映射纯函数、`AnthropicCompatAdapter.translate_stream`（text/收尾路径，THINKING/TOOL_USE 静默、ERROR 不发 message_stop）、`aggregate_message` 非流式聚合。
- `MessagesView`（adrf 非流式）+ `urls.py` 双注册（`/v1/messages` + `/v1/messages/`）：serializer 失败→Anthropic 400、`_build_runner` None→503、聚合为 Anthropic Messages 形状（content 仅正文、usage `input_tokens`/`output_tokens`）。
- 零回归：既有 OpenAI compat 全套 + 新增三文件共 94 passed；OpenAI 符号逐字不变、`progress.py` git diff 为空。

## Task Commits

1. **Task 1: serializer + 规整纯函数 + 单测** - `d75f0fb1a` (feat)
2. **Task 2: anthropic_adapter.py + error_handlers + 单测** - `de9d0650b` (feat)
3. **Task 3: MessagesView + urls 双注册 + view 级集成测** - `aea2ba567` (feat)

## Files Created/Modified
- `server/compat/anthropic_adapter.py` - Anthropic 专属 SSE 双行帧 + 事件骨架 + 映射 + adapter + aggregate_message
- `server/compat/schemas.py` - 新增 `_AnthropicMessageSerializer` / `AnthropicMessagesRequestSerializer`
- `server/compat/request_handler.py` - 新增 `anthropic_to_openai_messages` 规整纯函数
- `server/compat/error_handlers.py` - 新增 `anthropic_error_response`
- `server/compat/views.py` - 新增 `MessagesView`（非流式）
- `server/compat/urls.py` - 追加 `/v1/messages(+/)` 双注册
- `server/tests/compat/test_anthropic_schemas.py` - serializer + 规整纯函数单测（18）
- `server/tests/compat/test_anthropic_adapter.py` - 编码/事件/映射/adapter/aggregate 单测（16）
- `server/tests/compat/test_messages.py` - MessagesView 非流式 view 级集成测（5）

## Decisions Made
- **stream=True 暂走非流式聚合 + TODO(Plan 02)**：按 plan action 明确决策，删除 501/半成品流式犹豫项，功能可用、Plan 02 替换为真正 Anthropic SSE 双行帧流。
- **_status_to_stop_reason 恒 end_turn**：completed/interrupted/max_iterations 全映射 end_turn（D-3），预留 max_tokens 截断映射位。
- **aggregate_message / translate_stream 同源翻译核**：共用 `_rename_usage`/`_status_to_stop_reason`，content 仅 TEXT_DELTA 正文（P-8 零污染）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Task 1/Task 2 部分源码已预存于工作树（serializer / 规整纯函数 / error helper）**
- **Found during:** Task 1 / Task 2（读 schemas.py、request_handler.py、error_handlers.py 时发现已含目标符号，未提交）
- **Issue:** `AnthropicMessagesRequestSerializer`、`anthropic_to_openai_messages`、`anthropic_error_response` 已在工作树存在（疑似前序会话遗留）；其中 `error_handlers.py` 在我追加副本后出现 `anthropic_error_response` 重复定义（F811）。
- **Fix:** 复用已存在且与 plan 一致的实现；删除我追加的重复 `anthropic_error_response`，保留单一定义。
- **Files modified:** server/compat/error_handlers.py
- **Verification:** `ruff check` 通过、`pytest tests/compat/test_anthropic_adapter.py` 16 passed。
- **Committed in:** `de9d0650b`（Task 2 commit）

**2. [Rule 3 - Blocking] anthropic_adapter.py 的 `THINKING` import 被自动修复器剥离（F821）**
- **Found during:** Task 2（首次 `ruff check` 报 `Undefined name THINKING`）
- **Issue:** 写入后 import 行丢失 `THINKING`（疑似编辑器/格式化自动剔除「看似未用」导入），但 `aggregate_message` 引用了它。
- **Fix:** 在 `from agents.core.events import ...` 补回 `THINKING`。
- **Files modified:** server/compat/anthropic_adapter.py
- **Verification:** `ruff check` 通过、相关单测全绿。
- **Committed in:** `de9d0650b`（Task 2 commit）

---

**Total deviations:** 2 auto-fixed（1 Rule 1 预存源码去重、1 Rule 3 import 修复）
**Impact on plan:** 均为修正性改动，未扩大范围；最终符号集与 plan `<artifacts_this_phase_produces>` 完全一致，OpenAI 符号 / progress.py 零改动。

## DEVIATION D-1（计划内显式记录，同 Phase 56）
CONTEXT/里程碑默认假设 `TOOL_USE_*` 会流入 compat adapter。实证不符——`_build_runner()` 构造 `LangChainRunnerConfig` 不传 tools（`config.tools==[]`）→ runner 不 `bind_tools` → `TOOL_USE_*` 在 57 链路也**永不发射**。故 ANTHROPIC-02 的可见 trace 不能靠 `tool_event_to_progress`，必须由 `retrieval_to_progress`（真实 RAG 命中计数）经 thinking block 兑现（Plan 02）。本 Plan 01 只做非流式（不涉 trace），但 `translate_stream` 已按 index 单线性计数器 + 8 事件骨架纯函数齐备为 Plan 02 的 prelude/TOOL_USE 扩展留好结构。

## Issues Encountered
None - 计划顺利执行，仅上述两处自动修正。

## User Setup Required
None - 无外部服务配置。

## Next Phase Readiness
- ANTHROPIC-01（请求映射 + 非流式响应）已兑现，`POST /v1/messages` 返回合法 Anthropic Messages 形状。
- **Ready for 57-02**（流式 SSE 接线 + thinking block prelude + 真实 RAG 检索 progress 透出，兑现 ANTHROPIC-02）：`translate_stream` 文本/收尾路径与事件骨架已就位，Plan 02 仅需追加 prelude/TOOL_USE 分支与 view 层流式接线（替换当前 stream=True 的非流式 TODO）。

---
*Phase: 57-anthropic-messages*
*Completed: 2026-06-17*
