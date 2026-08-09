---
phase: 123-detect-changes
plan: 00
subsystem: testing
tags: [detect_changes, wave0, pytest, nyquist, DIFF-01, DIFF-02]

requires:
  - phase: 122-impact-trace
    provides: impact/trace dual-surface test patterns and run_impact orchestration
provides:
  - Four Wave 0 pytest stub files with collectable node names for W1–W5 verify anchors
  - Kernel zero-DB discipline for detect_changes overlap tests
  - Orchestrator/MCP skip stubs for base pin, hard reject, batch impact, dual-surface
affects: [123-01, 123-02, 123-03, 123-04, 123-05]

tech-stack:
  added: []
  patterns:
    - "Wave 0 skip stubs with reason Wave 0 桩：由 123-NN 落地 + pytest.fail body"
    - "Kernel tests: no django_db; shell/MCP tests: module pytestmark django_db"

key-files:
  created:
    - server/tests/services/code_graph/test_detect_changes.py
    - server/tests/services/test_diff_mirror.py
    - server/tests/services/code_graph/test_detect_changes_orchestrator.py
    - server/tests/mcp_tools/test_detect_changes_tools.py
  modified: []

key-decisions:
  - "Wave 0 only registers pytest nodes; no production code and no TOOL_SCHEMA_SNAPSHOT edits"
  - "DIFF-01/DIFF-02 requirements remain open until implementation plans (123-01+) land"
  - "MCP tools module docstring forbids mocking run_detect_changes for dual-surface integrity"

patterns-established:
  - "detect_changes kernel vs orchestrator file split mirrors test_impact.py / test_impact_shell.py"
  - "mcp_tools dual-surface file copies _reset_code_graph_state autouse (conftest scope gap)"

requirements-completed: []

duration: 1min
completed: 2026-08-09
---

# Phase 123 Plan 00: Wave 0 Test Skeleton Summary

**Nyquist Wave 0: four collectable pytest stub files covering DIFF-01/02 overlap, rename, formatting, threshold, orchestration, and MCP dual-surface node names for later plan verify commands.**

## Performance

- **Duration:** 1 min
- **Started:** 2026-08-09T18:31:04Z
- **Completed:** 2026-08-09T18:32:00Z
- **Tasks:** 2
- **Files modified:** 4 (created)

## Accomplishments

- Registered 9 kernel + 5 diff_mirror Wave 0 skip nodes (123-01 ownership)
- Registered 12 orchestrator + 5 MCP/dual-surface Wave 0 skip nodes (123-02..05 ownership)
- Confirmed `test_detect_changes.py` has zero `django_db` marks; production paths untouched
- `--collect-only` green for all 31 nodes across the four files

## Task Commits

Each task was committed atomically:

1. **Task 1: 纯内核 + diff_mirror 测试骨架** - `918071d7` (test)
2. **Task 2: 编排 + MCP/双面测试骨架** - `7158865a` (test)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `server/tests/services/code_graph/test_detect_changes.py` — zero-DB overlap/rename/formatting/threshold/exclusion stubs
- `server/tests/services/test_diff_mirror.py` — `--find-renames` / two-dot / rename / pin / byte-cap stubs
- `server/tests/services/code_graph/test_detect_changes_orchestrator.py` — base pin / hard reject / batch impact / staleness stubs
- `server/tests/mcp_tools/test_detect_changes_tools.py` — PAT / envelope / conversational / two_surfaces / trace stubs

## Decisions Made

- Left `requirements-completed` empty: Wave 0 only anchors verify nodes; DIFF-01/DIFF-02 close when 123-01+ implement behavior
- No production edits (`services/`, `mcp_tools/`, `agents/`, `mcp/` submodule, `repo_router_v2.py`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ROADMAP 6-column progress table not updated by SDK**
- **Found during:** State/roadmap updates after Task 2
- **Issue:** `roadmap.update-plan-progress` only handled 4/5-column tables; v0.22.0 progress table has 6 columns (Phase | Milestone | Requirements | Plans | Status | Completed), so Plans Complete stayed `0/6 | Planned`
- **Fix:** Manually set Phase 123 row to `1/6 | In Progress`; added 6-col branch in `.cursor/gsd-core/bin/lib/roadmap.cjs`
- **Files modified:** `.planning/ROADMAP.md`, `.cursor/gsd-core/bin/lib/roadmap.cjs`
- **Verification:** ROADMAP shows `1/6 | In Progress`; 123-00 checkbox `[x]`
- **Committed in:** docs commit for this plan

**2. [Rule 2 - Correctness] Did not mark DIFF-01/DIFF-02 complete**
- **Found during:** requirements.mark-complete step
- **Issue:** Plan frontmatter lists DIFF-01/DIFF-02, but Wave 0 only registers skip stubs
- **Fix:** Left REQUIREMENTS unchecked; documented in SUMMARY `requirements-completed: []`
- **Files modified:** none (intentional no-op)
- **Verification:** REQUIREMENTS.md still Pending for DIFF-01/02

## Threat Flags

None — Wave 0 is test harness only; threat mitigations are registered as skip nodes for later plans (T-123-ACL/EXCL/DOS/BASE/TRACE).

## Known Stubs

All Wave 0 nodes intentionally skipped with `pytest.fail("Wave 0 桩")` bodies — by design until 123-01..05 fill them.

| Stub | File | Reason |
|------|------|--------|
| 9 kernel tests | `test_detect_changes.py` | Filled by 123-01 |
| 5 mirror tests | `test_diff_mirror.py` | Filled by 123-01 |
| 12 orchestrator tests | `test_detect_changes_orchestrator.py` | Filled by 123-02 |
| 5 MCP/dual-surface tests | `test_detect_changes_tools.py` | Filled by 123-03/04/05 |

## Verification Results

```text
# Task 1
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_detect_changes.py \
  tests/services/test_diff_mirror.py --collect-only -q
→ 14 tests collected

# Task 2
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_detect_changes_orchestrator.py \
  tests/mcp_tools/test_detect_changes_tools.py --collect-only -q
→ 17 tests collected
```

## Self-Check: PASSED

- FOUND: all four test files
- FOUND: commits `918071d7`, `7158865a`
