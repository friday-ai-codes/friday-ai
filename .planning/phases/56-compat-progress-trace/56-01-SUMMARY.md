---
phase: 56-compat-progress-trace
plan: 01
subsystem: api
tags: [openai-compat, sse, reasoning_content, progress, trace, agent-events, inv-5]

# Dependency graph
requires:
  - phase: v0.7 (§15 event taxonomy)
    provides: 事件 taxonomy 语义词表（progress 文本释义对齐，非数据源）
  - phase: 既有 compat
    provides: OpenAICompatAdapter.translate_stream + THINKING→reasoning_content 范式 + sse_encode
provides:
  - "纯函数 compat progress 机制层 server/compat/progress.py（tool_event_to_progress + make_reasoning_chunk + 工具名映射表）"
  - "translate_stream TOOL_USE_START/RESULT → delta.reasoning_content progress 映射（前向兼容 / Phase 57 复用预埋）"
  - "四层守护测试（纯函数映射 / sentinel 安全 / adapter 集成 / 零回归 byte-eq）"
affects: [phase-57-anthropic-messages, compat-progress-plan-02-rag]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数 helper（事件→progress 文本 | None）与 adapter/view 解耦，便于独测 + 跨 adapter 复用"
    - "progress 经既有 reasoning_content 通道透出，绝不写 delta.tool_calls / finish_reason=tool_calls（INV-5 / TRACE-02）"

key-files:
  created:
    - server/compat/progress.py
    - server/tests/compat/test_progress.py
  modified:
    - server/compat/adapter.py
    - server/tests/compat/test_adapter.py

key-decisions:
  - "tool_event_to_progress 仅读 tool_name 查中文映射表；TOOL_USE_RESULT / 未知 / 缺名一律 None（保守静默，OQ-3）；绝不读 tool_input/result/error"
  - "make_reasoning_chunk 结构与既有 THINKING chunk 逐字一致（object=chat.completion.chunk / finish_reason=None / include_usage=True 带 usage=None）"
  - "不 import §15 event_taxonomy 常量驱动 progress（P-1，那套事件不在 AgentEvent 流，仅语义对齐）"
  - "DEVIATION D-1：compat 当前 _build_runner 不绑定 tools，TOOL_USE_* 永不发射 → 本 plan 是机制预埋 + 前向兼容；可见效果由 Plan 02 兑现"

patterns-established:
  - "纯函数机制层：progress 映射独立成模块，adapter 主循环只 yield，便于零回归/sentinel 断言"
  - "零回归 byte-eq：无工具事件序列 chunk 数与现状一致、不产空 progress chunk"

requirements-completed: [TRACE-01, TRACE-02]

# Metrics
duration: 11 min
completed: 2026-06-17
---

# Phase 56 Plan 01: compat progress 机制层 Summary

**纯函数 compat progress 机制层（工具名→中文语义映射 + reasoning_content chunk 构造）+ translate_stream TOOL_USE_* 映射分支，机制就位且严守 INV-5/TRACE-02，当前 compat 链路因无 tools 走降级（DEVIATION D-1，效果由 Plan 02 兑现）**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-17T10:51:14Z
- **Completed:** 2026-06-17T11:02:00Z
- **Tasks:** 3
- **Files modified:** 4（2 created + 2 modified）

## Accomplishments
- 新建 `server/compat/progress.py` 纯函数机制层：`tool_event_to_progress(evt)`（仅读 tool_name 查 `_TOOL_PROGRESS_LABELS` 中文映射表）+ `make_reasoning_chunk(common, text, include_usage)`（复用 `sse_encode`，结构与 THINKING chunk 逐字一致）。
- `translate_stream` 把原 `else: continue` 丢弃的 `TOOL_USE_START`/`TOOL_USE_RESULT` 改为独立映射分支：命中 yield `delta.reasoning_content` progress，返 None 则 continue（降级逐字等价、不产空 chunk）。
- 四层守护测试全部落地：纯函数映射（6.1）、安全 sentinel 不泄漏（6.4）、adapter 集成 + tool_calls 禁线（6.2）、零回归 byte-eq（6.3）。`tests/compat/` 17 → 43 passed。
- 守住 INV-5（progress 只含工具名高层语义，sentinel 全流不出现）与 TRACE-02（无 `delta.tool_calls`、无 `finish_reason="tool_calls"` 赋值）。

## Task Commits

每个任务原子提交：

1. **Task 1: 新建 progress.py 纯函数 helper + 映射表** - `eb2c6bff1` (feat)
2. **Task 2: translate_stream 接入 TOOL_USE_* → reasoning_content 映射** - `ae8783f0e` (feat)
3. **Task 3: 纯函数 + sentinel + adapter 集成 + 零回归 byte-eq 测试** - `4f7c1299e` (test)

**Plan metadata:** （本提交）docs(56-01)

## Files Created/Modified
- `server/compat/progress.py` (新建) - compat progress 纯函数机制层：工具名→中文语义映射表 + `tool_event_to_progress` + `make_reasoning_chunk`；只读 tool_name，绝不内联 tool_input/result/error；不 import event_taxonomy。
- `server/compat/adapter.py` (修改) - `translate_stream` 新增 `TOOL_USE_START/TOOL_USE_RESULT` 映射分支（None 静默 / 非空 yield reasoning_content）；顺带移除预存未使用导入 `AgentEvent` / `_omit`。
- `server/tests/compat/test_progress.py` (新建) - 纯函数映射单测（8 参数化 + 未知/缺名/RESULT 静默/非工具不误命中）+ sentinel 安全测 + make_reasoning_chunk 结构测。
- `server/tests/compat/test_adapter.py` (修改) - TOOL_USE_START 集成、未知工具不产 chunk、tool_calls 禁线、content 不污染、include_usage 一致、全流 sentinel、零回归 byte-eq。

## Decisions Made
- `TOOL_USE_RESULT` 一律静默（OQ-3）：本 plan 不透出完成态，F-6 计数派生留 Plan 02 的 retrieval_to_progress。
- progress 透出字段锁定 `delta.reasoning_content`（D-2），复用 THINKING 范式，客户端零适配成本。
- helper 放新模块 `server/compat/progress.py`（OQ-4）便于独测与 Phase 57（Anthropic thinking block）复用。
- 映射表覆盖 `search_rag`/`search_rag_chunks`→正在检索 RAG、`grep`→正在 grep 搜索、`get_file`→正在读取文件、`analyze_repository`/`route_repository`/`list_space_structure`/`find_related`→正在分析仓库。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug/Cleanup] 移除 adapter.py 预存未使用导入**
- **Found during:** Task 2（adapter.py 接入映射后跑 ruff）
- **Issue:** `agents.core.events.AgentEvent` 与 `.streaming._omit` 在 adapter.py 仅出现在 docstring，从无代码引用（预存 F401），阻塞 Task 2 的 `ruff check compat/adapter.py` 验证门禁。
- **Fix:** 从 import 块移除这两个未使用符号（不影响任何运行时行为）。
- **Files modified:** server/compat/adapter.py
- **Verification:** `ruff check compat/adapter.py` All checks passed；既有 9 个 adapter 测试零回归。
- **Committed in:** `ae8783f0e`（Task 2 commit）

**2. [Rule 1 - Cleanup] ruff --fix 整理新增/预存测试导入排序（I001）**
- **Found during:** Task 3（跑 ruff check tests/compat/）
- **Issue:** 新增 import 块及预存的两处函数内 import（test_adapter.py:338/357）被 ruff I001 标记未排序，阻塞验证门禁。
- **Fix:** `ruff check --fix` 自动整理导入（纯格式化，无语义变化）。
- **Files modified:** server/tests/compat/test_adapter.py, server/tests/compat/test_progress.py
- **Verification:** `ruff check` All checks passed；`tests/compat/` 43 passed。
- **Committed in:** `4f7c1299e`（Task 3 commit）

---

**Total deviations:** 2 auto-fixed（2 Rule 1 cleanup）。
**Impact on plan:** 均为通过验证门禁所需的最小清理，无语义变化、无 scope creep。

> **核心 DEVIATION（D-1，机制层非缺陷，已在 PLAN/RESEARCH 显式记录）**：CONTEXT 默认假设 `TOOL_USE_*` 会流入 compat `translate_stream`，**实证不符**——`_build_runner()` 构造 `LangChainRunnerConfig` 时不传 tools（`config.tools==[]`），runner 仅在有 tools 时 `bind_tools`，故 compat 链路下 `TOOL_USE_*` 永不发射。因此本 Plan 01 的 adapter 映射在**当前 compat 链路恒走降级、产 0 progress chunk**，属"机制预埋 + 前向兼容（未来 compat 绑定工具 / Phase 57 复用）"。TRACE-01 的**可见效果**由 Plan 02（真实 RAG 检索 progress 合成）兑现。两 Plan 合起来覆盖 RESEARCH 推荐的 Option C（A 机制 + B 效果）。

## Issues Encountered
None - 验证门禁触发两处预存 lint 清理（见 Deviations），均按 Rule 1 自修后全绿。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 机制层就位：纯函数 helper 与 adapter 解耦、可独测，Phase 57 Anthropic thinking block 可直接复用 `tool_event_to_progress` / 映射表。
- **Plan 02 待办**：在 view/stream 层围绕 `prepare_messages` 的 `HybridSearchService.search` 合成真实 RAG 检索 progress（"正在检索 RAG" / "检索完成，命中 N 处"），兑现 TRACE-01 可见效果（Option B）。

---
*Phase: 56-compat-progress-trace*
*Completed: 2026-06-17*

## Self-Check: PASSED

- key-files.created 均存在于磁盘（`server/compat/progress.py`、`server/tests/compat/test_progress.py`）。
- `git log --grep="56-01"` 返回 3 个任务提交（eb2c6bff1 / ae8783f0e / 4f7c1299e）。
- 全部 `<acceptance_criteria>` 复核通过：progress.py 含三符号且 grep 无 tool_input/result/error 读取与 event_taxonomy import（仅注释命中）；adapter 无 tool_calls 写入 / finish_reason=tool_calls 赋值（line 63 仅类型注解默认 "stop"）；行为断言由测试覆盖。
- plan-level `<verification>`：`uv run pytest tests/compat/ -q` → 43 passed；`ruff check compat/progress.py compat/adapter.py` → All checks passed。
