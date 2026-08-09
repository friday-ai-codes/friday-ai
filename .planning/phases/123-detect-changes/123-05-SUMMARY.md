---
phase: 123-detect-changes
plan: 05
subsystem: testing
tags: [D-13, D-27, dual-surface, detect_changes, IMPACT-06, tool_trace, nyquist]

# Dependency graph
requires:
  - plan: 123-03
    provides: "DetectChangesView MCP 壳 + run_detect_changes 接线"
  - plan: 123-04
    provides: "detect_changes @tool 对话壳 + 索引白名单"
provides:
  - "test_two_surfaces_same_payload_detect_changes —— 成功态 + repository_not_indexed 硬错误 byte-equal"
  - "ROADMAP D-27 mcp npm 漂移 7→8 记账（detect_changes）"
  - "123-VALIDATION wave_0_complete + nyquist_compliant"
affects: [124-code-chain-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "双面同源哨兵：json.dumps(sort_keys=True) 比对 MCP data（去 run_id）与 ToolResult.output.data"
    - "硬错误态走编排信封（空 last_indexed_commit_sha → repository_not_indexed），HTTP 200 + ToolResult.success=True"
    - "D-27 漂移记账必须写实扩大项数与工具名，禁止粉饰为无影响"

key-files:
  created: []
  modified:
    - server/tests/mcp_tools/test_detect_changes_tools.py
    - .planning/ROADMAP.md
    - .planning/phases/123-detect-changes/123-VALIDATION.md

key-decisions:
  - "硬错误轮选 repository_not_indexed（清空索引水位、保持 INDEXED）——两侧同走 run_detect_changes 折信封，避开壳层 400 早退分叉"
  - "D-27：漂移 7→8（新增 detect_changes），不修 mcp submodule、不改 package 对齐判据"
  - "registered 桩改为 agents 侧薄包装，避免双份 schema 断言"

patterns-established:
  - "detect_changes 双面哨兵与 impact/trace 同构：transaction=True + 禁 mock 编排层 + 键集先行 dumps"
  - "跨仓漂移台账句式：既有 N → Phase 新增工具 → N+k；本相位使失败从 X 扩大到 Y"

requirements-completed: [DIFF-01, DIFF-02]

# Metrics
duration: 6min
completed: 2026-08-09
---

# Phase 123 Plan 05: Dual-surface sentinel + D-27 ledger Summary

**MCP↔对话 detect_changes data 去 run_id 后 byte-equal（成功 + repository_not_indexed）；ROADMAP 写实 D-27 漂移 7→8；VALIDATION Nyquist 收口**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-08-09T18:56:05Z
- **Completed:** 2026-08-09T19:02:18Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- **双面同源哨兵（D-13）。** `test_two_surfaces_same_payload_detect_changes` 去掉 skip：同用户下成功态（mock 仅 mirror）与 `repository_not_indexed` 硬错误各一轮 `json.dumps(..., sort_keys=True)` 比对；`run_id` 写死为 MCP 面唯一允许差异。
- **观测无内容泄漏回归。** 既有 `test_tool_trace_payload_detect_changes_counts_only` 仍绿；`tool_trace_payload(detect_changes)` 无需改生产代码。
- **D-27 台账写实。** ROADMAP 跨仓记账升级为 7→8 + `detect_changes`；明文重申**不修** `mcp` submodule；声明本相位使既有失败从 7 **扩大到** 8。
- **VALIDATION 收口。** `wave_0_complete: true`、`nyquist_compliant: true`；Per-Task 表标绿；mcp package 对齐测继续列为已知既有失败。

## Task Commits

1. **Task 1: 双面同源哨兵（成功 + 硬错误）** - `fa6eb600` (test)
2. **Task 2: D-27 漂移 7→8 记账 + VALIDATION 收口** - `14010fae` (docs)

**Plan metadata:** docs commit（本 SUMMARY + STATE/ROADMAP/REQUIREMENTS）

## Files Created/Modified

- `server/tests/mcp_tools/test_detect_changes_tools.py` - 双面哨兵 + registered 薄包装；`_assert_surfaces_byte_equal`
- `.planning/ROADMAP.md` - D-27 7→8；Phase 123 Plans 6/6 勾选
- `.planning/phases/123-detect-changes/123-VALIDATION.md` - Wave0 / Nyquist 收口

## Decisions Made

- 硬错误用清空 `last_indexed_commit_sha`（壳层 INDEXED 闸仍放行）触发编排层 `repository_not_indexed` 信封，保证两侧同形可 byte-equal。
- 壳层与 `tool_trace_payload` 已由 123-02/03/04 落地，本 plan 无生产代码改动（哨兵即绿）。
- D-27 只改 ROADMAP/VALIDATION 文案；⛔ 不碰 `mcp/`、⛔ 不改 `test_mcp_package_alignment.py`。

## D-27 记账复述

- 既有 **5** 项（阶段沙箱工具）→ Phase 122 增 `impact_analysis` / `trace_call_path` → **7** 项。
- Phase 123 再增 `detect_changes` → **8** 项。
- 按 D-27 **不修** `mcp` submodule；守护继续红着。**本相位使既有失败从 7 扩大到 8——不是「没有影响」。**

## Requirements marking

- Plan frontmatter `requirements: [DIFF-01, DIFF-02]` → 本 plan 执行结束时经 `requirements.mark-complete` **标记 Complete**（相位本体成功标准已由 123-01..05 自动化覆盖）。

## Deviations from Plan

### Auto-fixed Issues

None - plan executed exactly as written.

### Notes (non-deviation)

- **TDD RED 门：** 双面壳已在 123-03/04 落地；本 task 的 RED 等价物是 Wave0 skip 桩。落地哨兵后首次跑测即绿，无需改 `code_graph_tools.py`。
- **mcp 工作区：** `git status --porcelain -- mcp` 显示既有 submodule 指针脏（并发会话），本 plan **零字节改动** `mcp/` 内容。

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 123 六 plan 全部完成；双面同源与 D-27 台账闭合。
- Phase 124 可接编码链闭环（容器自查 + MR 影响面报告），以本相位 `run_detect_changes` / MCP PAT 面为调用点。
- 已知遗留：`test_mcp_package_tools_match_server_snapshot` 仍红（8 项漂移，D-27 接受）。

## Scoped test results

```
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False
uv run pytest tests/mcp_tools/test_detect_changes_tools.py \
  tests/services/code_graph/test_detect_changes.py \
  tests/services/test_diff_mirror.py \
  tests/services/code_graph/test_detect_changes_orchestrator.py \
  tests/mcp_tools/test_impact_trace_tools.py \
  -k 'detect_changes or two_surfaces or diff_mirror or overlap or batch_impact or formatting or threshold or staleness or rename or hard_reject or base_ref or tool_trace' \
  -q --reuse-db
→ 34 passed, 4 deselected
```

## Self-Check: PASSED

- FOUND: `123-05-SUMMARY.md`, `test_detect_changes_tools.py`, `123-VALIDATION.md`
- FOUND commits: `fa6eb600`, `14010fae`
- FOUND dual-surface test + ROADMAP 7→8 / 「不修」mcp 文案

---
*Phase: 123-detect-changes*
*Completed: 2026-08-09*
