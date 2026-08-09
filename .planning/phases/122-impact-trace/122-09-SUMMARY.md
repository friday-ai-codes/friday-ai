---
phase: 122-impact-trace
plan: 09
subsystem: agents-tools
tags: [impact_analysis, trace_call_path, chat_runner, fail-closed, D-21, RetrievalTrace]

# Dependency graph
requires:
  - plan: 122-08
    provides: "run_impact / run_trace + resolve_tool_graph_branch / tool_trace_payload + MCP Serializer 上下界"
provides:
  - "impact_analysis / trace_call_path 对话 @tool 薄壳（fail-closed + 同源信封 + 留痕）"
  - "ImpactAnalysisToolInput / TraceCallPathToolInput pydantic 契约（与 MCP Serializer 同表）"
  - "_INDEXED_TOOL_NAMES 白名单两项 + tools/__init__ 注册"
affects: [122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "对话壳：_resolve_conversation_user 先于任何取仓/取图；ok=False/found=False 仍 ToolResult.success=True"
    - "output.data 原样透出编排返回值（AST Name）；metadata 只放对话面标量"
    - "注册 ≠ 暴露：__init__ 顶层 import + chat_runner 白名单缺一不可"

key-files:
  created:
    - server/agents/tools/graph_tools.py
    - server/agents/tools/schemas/graph_tools.py
  modified:
    - server/agents/tools/__init__.py
    - server/agents/chat_runner.py
    - server/agents/tools/delivery_knowledge_tools.py
    - server/tests/agents/tools/test_graph_tools.py

key-decisions:
  - "D-21：对话壳只调 run_impact / run_trace，data 段零加工"
  - "ok=False / found=False 走 success=True 信封，与 MCP HTTP 200 对齐"
  - "⛔ 不勾 IMPACT-06 Complete（双面齐备 + bookkeeping 归 122-10）"

patterns-established:
  - "非法 conversation_id 的 Django ValidationError 也必须 fail-closed 为无 owner"
  - "GraphError → graph_error_to_tool_error 映射文案；日志 error= 一律 redact_secrets_in_text"

requirements-completed: []  # IMPACT-06 需 MCP+对话双面齐备后由 122-10 勾 Complete

# Metrics
duration: 11min
completed: 2026-08-09
---

# Phase 122 Plan 09: Conversational impact/trace @tool shells Summary

**把 122-07 的 `run_impact` / `run_trace` 接到两个对话 `@tool` 薄壳：会话 owner fail-closed、同源信封、注册+白名单双挂，与 MCP 面共用编排与分支/留痕原语**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-08-09T17:34:44Z
- **Completed:** 2026-08-09T17:45:11Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- **pydantic 契约同表。** `ImpactAnalysisToolInput` / `TraceCallPathToolInput` 上下界与 MCP Serializer 逐条对齐（`strict + extra=forbid + frozen`）。
- **对话薄壳。** `impact_analysis` / `trace_call_path`：owner 闸 → 校验 → `_resolve_tool_repo` → `resolve_tool_graph_branch` → `run_*` → `data` 原样 + 一条 EDGE `RetrievalTrace` + `caller` 事件。
- **注册 ≠ 暴露。** `__init__.py` 顶层 import 与 `_INDEXED_TOOL_NAMES` 同步挂上；两用例落地（注册白名单 + owner fail-closed 下游零调用）。

## Task Commits

1. **Task 1: schemas + @tool 壳** - `802ba4e1` (feat)
2. **Task 2: 注册/白名单 + 用例** - `c429f84b` (feat)
3. **mypy hops 收窄** - `5c9caa72` (fix)

**Plan metadata:** (docs commit after this SUMMARY)

## Files Created/Modified

- `server/agents/tools/schemas/graph_tools.py` - 两个输入契约
- `server/agents/tools/graph_tools.py` - 两个对话工具壳
- `server/agents/tools/__init__.py` - 顶层 import + `__all__`
- `server/agents/chat_runner.py` - `_INDEXED_TOOL_NAMES` 增两项
- `server/agents/tools/delivery_knowledge_tools.py` - owner 解析捕获 Django ValidationError
- `server/agents/tools/schemas/api_tools.py` - ruff I001 空白行（验收门禁）
- `server/tests/agents/tools/test_graph_tools.py` - 两用例落地（零 skip）

## Decisions Made

- 遵循 D-21 / D-19：壳零算法、歧义交回 agent、`data` 与 MCP 同源。
- 不把编排层 `ok=False` 映射成 `ToolResult.success=False`。
- 未改 `mcp/` submodule；未碰 `loader.py` / `repo_router_v2.py`；未勾选 IMPACT-* Complete。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `_resolve_conversation_user` 未吞 Django ValidationError**
- **Found during:** Task 2（`test_conversation_owner_required_fail_closed` 非法 UUID）
- **Issue:** 非法 `conversation_id` 抬 `DjangoValidationError`，冒泡成工具校验错误而非 fail-closed 文案；安全上虽未取图，但用例/契约要求「无 owner」。
- **Fix:** `delivery_knowledge_tools._resolve_conversation_user` 捕获 `DjangoValidationError` / `TypeError` 返回 `None`。
- **Files modified:** `server/agents/tools/delivery_knowledge_tools.py`
- **Committed in:** `c429f84b`

**2. [Rule 3 - Blocking] `ruff check agents/` 被既有空白行挡住**
- **Found during:** Task 2 验收
- **Issue:** `schemas/api_tools.py` import 后双空行触发 I001
- **Fix:** 去掉多余空行
- **Files modified:** `server/agents/tools/schemas/api_tools.py`
- **Committed in:** `c429f84b`

**3. [Rule 1 - Bug] mypy：`len(hops)` 未收窄**
- **Found during:** 收尾 mypy
- **Issue:** `hops` 被推断为 `Any | list | None`
- **Fix:** 先赋 `hops_raw` 再 `isinstance` 收窄为 `list[Any]`
- **Files modified:** `server/agents/tools/graph_tools.py`
- **Committed in:** `5c9caa72`

---

**Total deviations:** 3 auto-fixed (1 missing critical, 1 blocking, 1 bug)
**Impact on plan:** 全部为正确性/门禁必需，无范围膨胀。

## Issues Encountered

- 并发会话有大量未提交改动；本 plan 仅按显式路径暂存，未触碰其文件。
- mypy 仍报告无关依赖文件既有错误；本 plan 目标文件已无本地错误。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 对话面与 MCP 面均已挂上同一编排；122-10 可跑 `test_two_surfaces_same_payload` 并勾 IMPACT-* Complete。

## Self-Check: PASSED

- Files: graph_tools / schemas/graph_tools / __init__ / chat_runner / test_graph_tools / SUMMARY — all FOUND
- Commits: `802ba4e1` / `c429f84b` — all FOUND
- Symbols: `impact_analysis` / `trace_call_path` in registry + `_INDEXED_TOOL_NAMES` — present
