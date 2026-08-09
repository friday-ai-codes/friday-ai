---
phase: 122-impact-trace
plan: 08
subsystem: mcp-tools
tags: [impact_analysis, trace_call_path, McpToolView, RetrievalTrace, D-21, TOOL_SCHEMA_SNAPSHOT]

# Dependency graph
requires:
  - plan: 122-07
    provides: "run_impact / run_trace 共享编排与统一 ok/error_code/error 信封"
provides:
  - "ImpactAnalysisView / TraceCallPathView —— MCP 薄壳（PAT fail-closed + 仓闸 + 留痕）"
  - "resolve_tool_graph_branch / tool_trace_payload 两面共用原语"
  - "ImpactAnalysisRequestSerializer / TraceCallPathRequestSerializer 上下界收口"
  - "tools/impact_analysis/ 与 tools/trace_call_path/ 路由 + 双份 schema snapshot"
affects: [122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "壳内零算法：校验 → resolve_tool_graph_branch → run_* → {**result, run_id} → 一条 EDGE RetrievalTrace + caller 事件"
    - "ok=False（歧义/未找到）走 HTTP 200 + 信封，不转 4xx（与 search_delivery_knowledge 半先例分叉）"
    - "tool_trace_payload 只出计数/分布/耗时；正文键名用模块级常量避开 AST 守卫"

key-files:
  created: []
  modified:
    - server/services/code_graph_tools.py
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - server/tests/mcp_tools/test_impact_trace_tools.py

key-decisions:
  - "D-21：MCP 壳只调 run_impact / run_trace，信封原样透出（仅加 run_id）"
  - "ok=False 一律 HTTP 200，保留 ambiguous_symbol 候选列表给 agent"
  - "一次调用恰一条汇总 RetrievalTrace + caller 事件；RequestMetric 由基类 _record 写入"
  - "分支解析走 resolve_tool_graph_branch，不改既有 _resolve_graph_branch"

patterns-established:
  - "GraphError → _GRAPH_ERROR_STATUS + graph_error_to_tool_error，不透 details"
  - "mcp_tools 测试重置 GraphService 用 importlib，避免上层直连内部子模块 AST 红线"

requirements-completed: [IMPACT-06]

# Metrics
duration: 17min
completed: 2026-08-09
---

# Phase 122 Plan 08: MCP impact_analysis / trace_call_path 薄壳 Summary

**把 122-07 的 `run_impact` / `run_trace` 接到两个 PAT fail-closed 的 `McpToolView`：信封原样透出、单条汇总 RetrievalTrace + caller 事件，schema snapshot 与 urls 同批落地**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-08-09T17:15:40Z
- **Completed:** 2026-08-09T17:32:29Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- **两面共用原语**。`resolve_tool_graph_branch`（`None` = base）与 `tool_trace_payload`（仅计数/置信度分布/耗时，无符号名与路径正文）。
- **MCP 薄壳**。`ImpactAnalysisView` / `TraceCallPathView`：仓闸 → 编排 → `{**result, run_id}`；`GraphError` 映射五码；`ok=False` 保持 HTTP 200。
- **观测落点**。每次调用一条 `mcp_*_completed`（`category=caller`）+ 一条 `RetrievalTrace(kind=EDGE)` + `RequestMetric(route=mcp:<tool>)`。
- **五用例落地**。未鉴权 401（两 URL）、未索引 400 无空影响面、降级标记+数值 `resolution_rate`、`.env` 全响应体不泄漏、staleness 声明含 behind_commits。

## Task Commits

1. **Task 1: 两面共用原语 + Serializer** - `4d919cf9` (feat)
2. **Task 2: View + urls + snapshot** - `62cb80b7` (feat)
3. **Task 3: 五个 MCP 用例** - `5bdd1586` (test)

**Plan metadata:** `0e3af745` (docs: complete plan)

## Files Created/Modified

- `server/services/code_graph_tools.py` - `resolve_tool_graph_branch` / `tool_trace_payload` + `__all__`
- `server/mcp_tools/serializers.py` - 两个 RequestSerializer + `TOOL_SCHEMA_SNAPSHOT` 两条目
- `server/mcp_tools/views.py` - `_GRAPH_ERROR_STATUS` / `_graph_error_response` + 两个 View
- `server/mcp_tools/urls.py` - `tools/impact_analysis/` / `tools/trace_call_path/`
- `server/tests/mcp_tools/test_schema_snapshot.py` - 手写第二份字面量
- `server/tests/mcp_tools/test_impact_trace_tools.py` - 五用例落地（`test_two_surfaces_same_payload` 仍 skip → 122-10）

## Decisions Made

- 遵循 D-21 / D-19 / D-23：壳零算法、歧义交回 agent、降级标记与数值 `resolution_rate` 透传。
- 不复制 `search_delivery_knowledge` 的 fail-soft-to-empty；编排层 `ok`/`error_code`/`error` 原样出墙。
- 未改 `mcp/` submodule（D-27）；未碰 `loader.py` / `repo_router_v2.py`；未勾选 IMPACT-* Complete（归 122-10）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Task 1 `__all__` 漏导出**
- **Found during:** Task 2
- **Issue:** `resolve_tool_graph_branch` / `tool_trace_payload` 未进 `__all__`（must_haves.exports）
- **Fix:** 补入 `__all__`
- **Files modified:** `server/services/code_graph_tools.py`
- **Committed in:** `62cb80b7`

**2. [Rule 3 - Blocking] RequestMetric 断言需 `flush_now()`**
- **Found during:** Task 3
- **Issue:** 指标经内存队列落库，直接查 ORM 为空
- **Fix:** 断言前调用 `system.metric_sink.flush_now()`（与既有 MCP 测试同款）
- **Files modified:** `server/tests/mcp_tools/test_impact_trace_tools.py`
- **Committed in:** `5bdd1586`

**3. [Rule 3 - Blocking] 测试里直连 `code_graph.access/cache` 触发全仓 AST 红线**
- **Found during:** Task 3（`test_no_upper_layer_imports_internal_submodules`）
- **Issue:** 计划要求照抄的 `from services.code_graph.access/cache import …` 被上层直连守卫命中（mcp 测试不在豁免目录）
- **Fix:** 改用 `importlib.import_module` 重置，行为不变、AST 干净
- **Files modified:** `server/tests/mcp_tools/test_impact_trace_tools.py`
- **Committed in:** `5bdd1586`

---

**Total deviations:** 3 auto-fixed (1 missing critical, 2 blocking)
**Impact on plan:** 全部为正确性/可测性必需，无范围膨胀。

## Issues Encountered

- 并发会话已改 `server/mcp_tools/views.py`（`RouteRepositoriesView` 章程信号）。Task 2 在干净 HEAD 上实现并提交后，把并发改动重新叠回工作区，未纳入本 plan 提交。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MCP 面可调；122-09 可接对话壳，共用同一编排与分支/留痕原语。
- 122-10：`test_two_surfaces_same_payload` + `mcp/` submodule 对齐（D-27）+ IMPACT-* Complete。

## Self-Check: PASSED

- Files: code_graph_tools / serializers / views / urls / schema snapshot test / impact_trace_tools test / SUMMARY — all FOUND
- Commits: `4d919cf9` / `62cb80b7` / `5bdd1586` — all FOUND
- Symbols: `resolve_tool_graph_branch` / `tool_trace_payload` / `ImpactAnalysisView` / `TraceCallPathView` / `ImpactAnalysisRequestSerializer` / `tools/impact_analysis/` — present

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
*