---
phase: 126-process-rename-skills
plan: 03
subsystem: code_graph
tags: [affected-processes, impact-report, mcp, agents, process-query, D-06, D-07, D-08]

requires:
  - phase: 126-process-rename-skills
    provides: ProcessTrace ORM + BFS rebuild + Wave 0 Nyquist stubs
  - phase: 122-impact-trace-tools
    provides: run_impact / MCP+agents dual-face + envelope shape
  - phase: 123-detect-changes
    provides: run_detect_changes + affected_processes placeholder
  - phase: 124-coding-chain
    provides: build_impact_report_section formatter
provides:
  - assemble_affected_processes single dialect + impact/detect_changes backfill
  - impact_report「受影响执行流」narrative (empty-safe)
  - run_list_processes / run_get_process + MCP/agents thin shells + call-through tests
affects:
  - 126-04 rename_preview dual-face shells (same thin-shell pattern)
  - MR create_merge_request / coding node via shared impact_report formatter

tech-stack:
  added: []
  patterns:
    - "Single assemble_affected_processes helper; batch detect_changes loads ProcessTrace once"
    - "Dual-face process query: shared run_* + MCP View / agents @tool thin shells"
    - "impact_report consumes envelope.affected_processes; no Phase 126 placeholder"

key-files:
  created:
    - server/services/code_graph/affected_processes.py
  modified:
    - server/services/code_graph_tools.py
    - server/services/code_graph/impact_report.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/mcp_tools/serializers.py
    - server/agents/tools/graph_tools.py
    - server/agents/tools/schemas/graph_tools.py
    - server/agents/tools/__init__.py
    - server/agents/chat_runner.py
    - server/tests/services/code_graph/test_affected_processes.py
    - server/tests/services/code_graph/test_impact_report.py
    - server/tests/services/code_graph/test_process_query.py
    - server/tests/mcp_tools/test_schema_snapshot.py

key-decisions:
  - "assemble_affected_processes lives in code_graph/affected_processes.py (pure); tools re-export + call sites"
  - "detect_changes batch path: one ProcessTrace.filter(repo, branch=\"\") after impacts; no N+1"
  - "list_processes default sort: cross_community → intra → empty; chat_runner whitelist required for LLM visibility"
  - "D-27 npm mcp client drift 8→10 (list_processes + get_process); submodule untouched"

patterns-established:
  - "Process query observability: list_processes_*/get_process_* started/completed/failed + duration_ms + category/component"
  - "RetrievalTrace for process tools is count-only (no steps body)"

requirements-completed: [EXEC-02, EXEC-03]

duration: 8min
completed: 2026-08-10
---

# Phase 126 Plan 03: Dual-face Process Query + Affected Backfill Summary

**Shared `assemble_affected_processes` fills impact/detect_changes envelopes; MR Affected renders execution-flow narrative; MCP/agents list+get Process via thin shells with forced call-through tests.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-08-09T21:16:13Z
- **Completed:** 2026-08-09T21:23:43Z
- **Tasks:** 3/3 (TDD RED→GREEN each)
- **Files modified:** 14

## Accomplishments

- Single-dialect `assemble_affected_processes` wired into `run_impact` and `run_detect_changes` (batch one-shot ProcessTrace load)
- `build_impact_report_section` Affected shows「受影响执行流」or empty short declaration; Phase 126 placeholder removed
- `run_list_processes` / `run_get_process` + MCP Views + agents `@tool` + chat whitelist; observability lifecycle complete
- Schema snapshot updated for server tools; npm `mcp/` client drift accounted **8→10**

## Task Commits

Each task was committed atomically (TDD):

1. **Task 1: assemble_affected_processes + 双编排回填（D-07）** — RED `8a617fd2` (test) → GREEN `a7dac456` (feat)
2. **Task 2: impact_report 受影响执行流段（D-08）** — RED `7864b02c` (test) → GREEN `60b961e6` (feat)
3. **Task 3: list/get Process 共享编排 + MCP/对话薄壳（D-06）** — RED `8586365c` (test) → GREEN `0074756a` (feat)

## Files Created/Modified

- `server/services/code_graph/affected_processes.py` — pure assemble + hit collectors
- `server/services/code_graph_tools.py` — backfill + `run_list_processes` / `run_get_process` + logs
- `server/services/code_graph/impact_report.py` — Affected 执行流段；Recommendations 去占位句
- `server/mcp_tools/{views,urls,serializers}.py` — ListProcessesView / GetProcessView + snapshot
- `server/agents/tools/graph_tools.py` (+ schemas / `__init__` / `chat_runner.py`) — dual-face + whitelist
- Wave 0 tests unskipped/rewritten for affected / process_query / impact_report / schema_snapshot

## Decisions Made

- Helper module under `services/code_graph/` (no ORM) keeps D-01 package boundary; orchestration loads rows
- `get_process` includes `steps`; `list_processes` omits step bodies (token discipline)
- Auto-added `chat_runner._INDEXED_TOOL_NAMES` entries (Rule 2 — register ≠ expose)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] chat_runner whitelist for new tools**
- **Found during:** Task 3
- **Issue:** Plan file list omitted `chat_runner.py`; without whitelist LLM cannot see tools
- **Fix:** Added `list_processes` / `get_process` to `_INDEXED_TOOL_NAMES`
- **Files modified:** `server/agents/chat_runner.py`
- **Committed in:** `0074756a`

**2. [Rule 1 - Bug] MCP call-through test must await async view**
- **Found during:** Task 3 GREEN
- **Issue:** Sync `as_view()(req)` left coroutine unawaited → mock never called
- **Fix:** Async test + await response
- **Files modified:** `server/tests/services/code_graph/test_process_query.py`
- **Committed in:** `0074756a`

**Total deviations:** 2 auto-fixed (Rule 2 ×1, Rule 1 ×1)

## npm Client Schema Drift (D-27 / D-16)

| Prior | This plan | Delta tools |
|-------|-----------|-------------|
| 8 | **10** | `list_processes`, `get_process` |

`mcp/` git submodule **not edited**. `test_mcp_package_tools_match_server_snapshot` remains an expected known failure until npm client follow-up.

## Threat Flags

None beyond plan register — new MCP endpoints reuse PAT fail-closed + `_get_indexed_repo` ACL (T-126-01); RetrievalTrace count-only (T-126-03); submodule untouched (T-126-06).

## Known Stubs

None — Wave 0 skips removed; no placeholder UI/data paths left for this plan's goals.

## Verification

```text
cd server && GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_process_query.py \
  tests/services/code_graph/test_affected_processes.py \
  tests/services/code_graph/test_impact_report.py \
  tests/mcp_tools/test_schema_snapshot.py -q --reuse-db
→ 22 passed
```

Frozen surfaces: `repo_router_v2.py` and `mcp/` not in any 126-03 commit.

## Self-Check: PASSED

- FOUND: `server/services/code_graph/affected_processes.py`
- FOUND: `assemble_affected_processes` in `code_graph_tools.py` (≥3 refs)
- FOUND: commits `8a617fd2`, `a7dac456`, `7864b02c`, `60b961e6`, `8586365c`, `0074756a`
- FOUND: no `待 Phase 126` in `impact_report.py`
- CONFIRMED: frozen surfaces clean in plan commits
