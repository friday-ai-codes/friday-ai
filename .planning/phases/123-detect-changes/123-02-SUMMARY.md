---
phase: 123-detect-changes
plan: 02
subsystem: code-intelligence
tags: [detect_changes, run_detect_changes, orchestrator, tool_trace_payload, DIFF-01, DIFF-02]

requires:
  - phase: 123-01
    provides: diff_mirror / ensure_mirror_sha + detect_changes pure overlap kernel
  - phase: 122-impact-trace
    provides: run_impact / staleness_payload / degradation_payload / tool_trace_payload shape
provides:
  - run_detect_changes unique orchestrator (ACL → pin base → overlap → threshold → sequential run_impact)
  - tool_trace_payload detect_changes counts-only branch
  - Green orchestrator + tool_trace Wave 0 stubs for 123-02 scope
affects: [123-03, 123-04, 123-05]

tech-stack:
  added: []
  patterns:
    - "diff base forced via ensure_mirror_commit() with no branch; base_ref output-only"
    - "batch impact = sequential run_impact(symbol_id=…, graph_branch=None); >100 seeds zero calls"
    - "tool_trace_payload(detect_changes) counts only — files_touched/impacts_ok|failed/truncated"

key-files:
  created: []
  modified:
    - server/services/code_graph_tools.py
    - server/tests/services/code_graph/test_detect_changes_orchestrator.py
    - server/tests/mcp_tools/test_detect_changes_tools.py

key-decisions:
  - "compare == index waterline → ok=False error_code=empty_diff_range (not silent empty success)"
  - "Truncation path fills graph via one fetch_graph_for_tool(depth=1) or numeric placeholder (A5)"
  - "DIFF-01/DIFF-02 left Pending until MCP/conversational shells land (123-03+)"

patterns-established:
  - "run_detect_changes is the only orchestration entry; shells must pass through unchanged"
  - "caller lifecycle events code_graph_detect_changes_{started,completed,failed} on sibling module"

requirements-completed: []

duration: 7min
completed: 2026-08-09
---

# Phase 123 Plan 02: run_detect_changes Orchestrator Summary

**Shared `run_detect_changes` orchestrator pins diff base to `last_indexed_commit_sha`, overlaps ORM Symbols on base graph, gates batch impact at 100 seeds, and emits counts-only `tool_trace_payload` for detect_changes.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-08-09T18:39:14Z
- **Completed:** 2026-08-09T18:45:39Z
- **Tasks:** 2 (Task 1 TDD RED→GREEN; Task 2 feat)
- **Files modified:** 3

## Accomplishments

- Landed `run_detect_changes`: ACL-first, index pin, MirrorError hard-reject, exclusion, sequential `run_impact`, 122-shaped envelope with `staleness` / `graph` / `affected_processes=[]`
- Threshold (>100 seeds) skips all `run_impact` and still fills numeric `resolution_rate` graph payload
- Extended `tool_trace_payload` for `detect_changes` with counts only (T-123-TRACE)

## Task Commits

Each task was committed atomically (TDD for Task 1):

1. **Task 1 RED: orchestrator failing tests** - `adc47e8f` (test)
2. **Task 1 GREEN: run_detect_changes** - `1b7dcf6b` (feat)
3. **Task 2: tool_trace_payload detect_changes** - `11d5f749` (feat)

**Plan metadata:** _(see final docs commit hash below / git log)_

## Files Created/Modified

- `server/services/code_graph_tools.py` — `run_detect_changes` + detect_changes `tool_trace_payload` branch + caller lifecycle events
- `server/tests/services/code_graph/test_detect_changes_orchestrator.py` — 12 green orchestration contract tests
- `server/tests/mcp_tools/test_detect_changes_tools.py` — `test_tool_trace_payload_detect_changes_counts_only` green (other MCP/对话 stubs remain for 123-03+)

## Decisions Made

- `empty_diff_range` when compare resolves to the same sha as the index waterline (Pitfall 6)
- Batch impact stays a sequential for-loop with impact_analysis defaults (`max_depth=3`, `min_confidence=1.0`, `graph_branch=None`)
- Did not mark DIFF-01/DIFF-02 Complete — dual-surface shells still pending

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Correctness] Left DIFF-01/DIFF-02 requirements Pending**
- **Found during:** State/requirements updates after Task 2
- **Issue:** Plan frontmatter lists DIFF-01/DIFF-02, but full REQ text still needs MCP/conversational wiring (123-03+)
- **Fix:** `requirements-completed: []`; skipped `requirements.mark-complete`
- **Files modified:** none (intentional no-op)
- **Verification:** REQUIREMENTS.md remains Pending for DIFF-01/02

**2. [Rule 1 - Bug] Formatting fixture trailing whitespace tripped ruff W291**
- **Found during:** Task 1 GREEN ruff gate
- **Issue:** Intentional trailing spaces in `_FORMATTING_DIFF` triple-quoted string
- **Fix:** Build the `+` line via string concat so source has no trailing whitespace
- **Files modified:** `server/tests/services/code_graph/test_detect_changes_orchestrator.py`
- **Committed in:** `1b7dcf6b`

**Total deviations:** 2 (1 intentional requirements timing, 1 lint fixture fix)
**Impact on plan:** No scope creep; orchestrator + trace counts match acceptance criteria.

## Issues Encountered

None blocking. Orchestrator suite ~45s under scoped env (DB fixture warm).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for 123-03 MCP shell and 123-04 conversational shell to call `run_detect_changes` and pass through the envelope
- Envelope keys stable: `ok,tool,repository_id,diff_base_sha,diff_head_sha,base_ref?,files,impacts,summary,affected_processes,staleness,graph`

## Verification Results

```text
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_detect_changes_orchestrator.py \
  tests/mcp_tools/test_detect_changes_tools.py::test_tool_trace_payload_detect_changes_counts_only \
  -q --reuse-db
# 13 passed
```

## TDD Gate Compliance

- RED: `adc47e8f` (`test(123-02): …`)
- GREEN: `1b7dcf6b` (`feat(123-02): …`)
- Task 2 was non-TDD `type=auto` as planned

## Self-Check: PASSED

- SUMMARY / `code_graph_tools.py` / orchestrator + tool_trace tests present
- Commits `adc47e8f`, `1b7dcf6b`, `11d5f749` present in git log
- No TODO/FIXME stubs blocking plan goal
