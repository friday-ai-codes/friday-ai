---
phase: 122-impact-trace
plan: 07
subsystem: code-graph
tags: [run_impact, run_trace, D-21, orchestrator, ambiguous-short-circuit, subgraph-uncertainty]

# Dependency graph
requires:
  - plan: 122-02
    provides: "resolve_symbol_in_graph / SymbolResolution"
  - plan: 122-03
    provides: "analyze_impact / grade_risk / RiskLevel"
  - plan: 122-04
    provides: "trace_path / equal_length_path_count / no_path structure"
  - plan: 122-05
    provides: "fetch_graph_for_tool / staleness_payload / degradation_payload / resolve_symbol_candidates"
  - plan: 122-06
    provides: "collect_cross_repo_impact / DEFAULT_MAX_CROSS_REPO_HOPS"
provides:
  - "run_impact / run_trace —— MCP 与对话两面共用的唯一编排入口（D-21）"
  - "统一失败语义 ok / error_code / error；GraphError 唯一上抛"
  - "重名在取图之前短路；found=False 保持 ok=True（D-20）"
  - "_TRACE_SEED_DEPTH=3 + 按需子图无路径补充声明"
affects: [122-08, 122-09, 122-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "共享编排函数收口失败语义（对照 search_delivery_knowledge 的漂移反面教材）"
    - "circular import：collect_cross_repo_impact 函数体内 lazy import"
    - "AST 单点守护 analyze_impact / trace_path 仅在 code_graph_tools.py 内各 1 次"

key-files:
  created: []
  modified:
    - server/services/code_graph_tools.py
    - server/tests/services/code_graph/test_impact_shell.py

key-decisions:
  - "D-21：两壳只调 run_impact / run_trace，逻辑不许在壳里分叉"
  - "D-19：歧义 ok=False + candidates，绝不静默取第一个；短路在取图之前"
  - "D-20：found=False 仍 ok=True——无路径是成功查询结果"
  - "D-24：run_trace 双种子 + _TRACE_SEED_DEPTH=3；子图无路径追加补充声明"
  - "max_cross_repo_hops 默认 None 再解析 DEFAULT_MAX_CROSS_REPO_HOPS，避免与 code_graph_cross_repo 顶层循环导入"

patterns-established:
  - "编排层不 catch GraphError；壳层才 graph_error_to_tool_error"
  - "symbol_not_in_graph 响应不含 groups 键（空影响面误导）"

requirements-completed: []  # 壳层 122-08/09 未接线；⛔ 不得勾选 IMPACT-* Complete

# Metrics
duration: 8min
completed: 2026-08-09
---

# Phase 122 Plan 07: 共享编排入口 run_impact / run_trace Summary

**把 122-02～122-06 的零件收成两个唯一编排函数：`run_impact` / `run_trace` 固定失败语义与声明信封，重名在取图前短路，按需子图上的无路径必须声明不确定性——两壳从此只能调它们、不能各写一份**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-08-09T17:05:44Z
- **Completed:** 2026-08-09T17:13:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- **`run_impact` 五步编排**。ORM `resolve_symbol_candidates` → `fetch_graph_for_tool(seed, depth=max_depth)` → `resolve_symbol_in_graph` → `analyze_impact`（本文件唯一调用点）→ `collect_cross_repo_impact` 后按成功/折叠条目重算 `risk_level`。成功态 15 键信封恒带 `staleness` 与数值 `resolution_rate` 的 `graph` 段。
- **统一失败语义**。`ok` / `error_code` / `error` 三键；`symbol_not_found` / `ambiguous_symbol` / `symbol_not_in_graph` 走 `ok=False`；`GraphError` 原样上抛（用例钉死 `GraphNotIndexed`，不是空 groups）。
- **`run_trace` 同构**。两端各自解析；歧义填 `source_resolution` / `target_resolution`，另一端给已解析 id；`seed_symbol_ids=[source, target]` + `_TRACE_SEED_DEPTH=3`；`found=False` 时 `ok` 仍为 `True`；按需子图无路径追加「超出子图覆盖范围」声明。
- **验收全绿**。`test_ambiguous_symbol_short_circuits_before_graph_fetch` 落地（spy `call_count==0`）；`test_run_trace_no_path_on_subgraph_declares_uncertainty` 用 10 跳链 + `CODE_GRAPH_MAX_GRAPH_BYTES=1` 逼出子图落差；AST 断言 `analyze_impact` / `trace_path` 在本文件内各 1 次。

## Task Commits

1. **Task 1: run_impact —— 五步编排与统一输出信封** - `f0de71fc` (feat)
2. **Task 2: run_trace —— 双端解析与同款信封** - `ec7f16af` (feat)

## Files Created/Modified

- `server/services/code_graph_tools.py`（~993 行）— 追加 `run_impact` / `run_trace`、`_TRACE_SEED_DEPTH`、`_SUBGRAPH_NO_PATH_DECLARATION` 与辅助 `_branch_label` / `_seed_from_graph` / `_crosses_repo_from_entries` / `_regrade_with_cross_repo`。
- `server/tests/services/code_graph/test_impact_shell.py` — 摘掉 Wave 0 skip；新增 7 条用例（impact 4 + trace 4，含歧义短路复用），本文件 **11 passed / 0 skipped**。

## Decisions Made

- **循环导入用函数体内 lazy import**：`code_graph_cross_repo` 顶层依赖本文件原语，故 `collect_cross_repo_impact` / `DEFAULT_MAX_CROSS_REPO_HOPS` 在 `run_impact` 内导入；`max_cross_repo_hops` 签名默认 `None`，进入后填默认值 1。
- **穿仓重算只计成功与折叠**：`unavailable` 不抬 `crosses_repo`，避免临时故障把风险抬到 HIGH。
- **`user` 必填关键字参数**：把两面用户来源差异收进签名（PATTERNS D-21 债）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `max_cross_repo_hops` 默认改为 `None` + lazy 解析**
- **Found during:** Task 1
- **Issue:** 顶层 `from services.code_graph_cross_repo import DEFAULT_MAX_CROSS_REPO_HOPS` 与该模块对本文件的顶层 import 形成环。
- **Fix:** 函数体内 lazy import；默认参数用 `None` 哨兵再填 `DEFAULT_MAX_CROSS_REPO_HOPS`。
- **Files modified:** `server/services/code_graph_tools.py`
- **Commit:** `f0de71fc`

**2. [Rule 1 - Bug] GraphNotIndexed 用例须先落 ORM 符号**
- **Found during:** Task 1 acceptance
- **Issue:** 无符号时 `symbol_not_found` 短路在取图之前，测不到「不吞 GraphError」。
- **Fix:** 先建符号再撤 `index_status`，用 `symbol_id` 调用。
- **Files modified:** `server/tests/services/code_graph/test_impact_shell.py`
- **Commit:** `f0de71fc`

**Total deviations:** 2 auto-fixed (1× Rule 3, 1× Rule 1)
**Impact on plan:** 行为与验收不变；签名上 `max_cross_repo_hops` 默认从字面常量变为 `None`→解析，壳层不传时仍得默认 1。

## Verification Results

| 判据 | 结果 |
|---|---|
| `pytest tests/services/code_graph -q --reuse-db` | **130 passed / 2 deselected / 0 skipped**（基线 122/1 skip；+8 passed、skip 清零） |
| `test_impact_shell.py` | **11 passed** |
| `test_run_trace_no_path_on_subgraph_declares_uncertainty` | 通过 |
| AST `analyze_impact` / `trace_path` 各 1 次 | 退出码 0 |
| 签名同构（共享 KW_ONLY 参数） | 退出码 0 |
| `ruff check`（本 plan 2 文件） | All checks passed |
| `mypy services/code_graph_tools.py` | **本文件零错误**（报出的 5 条在既有无关模块） |
| `makemigrations --check --dry-run` | `No changes detected` |
| `git diff` 本 plan 两提交 | 仅上述 2 文件；**不含** `repo_router_v2.py` / `loader.py` / `mcp/` |

## Issues Encountered

None beyond the two documented deviations.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **122-08 / 122-09** 可接壳：校验 → `run_impact` / `run_trace` → 渲染 → 留痕；`GraphError` 在壳层经 `graph_error_to_tool_error` 翻译。
- ⛔ 勿复制 `search_delivery_knowledge` 的双份手写参数；两面必须产出 byte-identical `data`。
- IMPACT-* 仍未 Complete（壳未接线；跨仓路径仍受 D-26 零样本约束）。

## Known Stubs

- `affected_processes: []` —— 内核预留位，叙事层归 Phase 126；本 plan 信封透传空列表属契约占位，非半截功能。

## Self-Check: PASSED

- `FOUND: server/services/code_graph_tools.py`（含 `run_impact` / `run_trace`）
- `FOUND: server/tests/services/code_graph/test_impact_shell.py`
- `FOUND: f0de71fc` / `FOUND: ec7f16af`
- `FOUND: .planning/phases/122-impact-trace/122-07-SUMMARY.md`

---
*Phase: 122-impact-trace*
*Completed: 2026-08-09*
