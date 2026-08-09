---
phase: 123-detect-changes
plan: 03
subsystem: code-intelligence
tags: [detect_changes, mcp, DetectChangesView, TOOL_SCHEMA_SNAPSHOT, DIFF-01, DIFF-02]

requires:
  - phase: 123-02
    provides: run_detect_changes unique orchestrator + tool_trace_payload detect_changes
  - phase: 122-impact-trace
    provides: ImpactAnalysisView MCP thin-shell pattern
provides:
  - DetectChangesRequestSerializer (compare + optional base_ref; no branch overlay)
  - DetectChangesView MCP thin shell → run_detect_changes
  - tools/detect_changes/ url + TOOL_SCHEMA_SNAPSHOT entry
  - Green MCP PAT + success envelope tests
affects: [123-04, 123-05]

tech-stack:
  added: []
  patterns:
    - "MCP shell zero-algorithm: validate → _get_indexed_repo → run_detect_changes → passthrough + run_id"
    - "compare required / base_ref declarative-only; no branch graph overlay (D-02)"
    - "ok=False stays HTTP 200; MirrorError folded by orchestrator, shell catch is fallback"

key-files:
  created: []
  modified:
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/mcp_tools/urls.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - server/tests/mcp_tools/test_detect_changes_tools.py

key-decisions:
  - "Serializer rejects control chars / .. on compare; local _SAFE_COMPARE_RE mirror of repo_mirror"
  - "views.py commit excluded concurrent RouteRepositoriesView charter WIP (selective stage)"
  - "DIFF-01/DIFF-02 left Pending until conversational + dual-surface plans land (123-04/05)"

patterns-established:
  - "DetectChangesView mirrors ImpactAnalysisView; component=mcp_tools caller event mcp_detect_changes_completed"
  - "MCP tests mock mirror helpers only — never mock run_detect_changes"

requirements-completed: []

duration: 2min
completed: 2026-08-09
---

# Phase 123 Plan 03: MCP Surface Summary

**PAT-gated `detect_changes` MCP shell delegates 100% to `run_detect_changes`, with serializer/schema snapshot/url landing in the same wave (D-13 / D-02).**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-09T18:48:56Z
- **Completed:** 2026-08-09T18:51:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `DetectChangesRequestSerializer` (`compare` required, `base_ref` optional, impact-aligned DoS bounds; no `branch` overlay)
- Added `TOOL_SCHEMA_SNAPSHOT["detect_changes"]` + literal twin in `test_schema_snapshot.py`
- Landed `DetectChangesView` thin shell + `tools/detect_changes/` route with RetrievalTrace + caller observability
- Greened `test_mcp_detect_changes_requires_pat` and `test_mcp_detect_changes_success_envelope` (mock mirror only)

## Task Commits

Each task was committed atomically:

1. **Task 1: Serializer + TOOL_SCHEMA_SNAPSHOT** - `55924415` (feat)
2. **Task 2: DetectChangesView + url + MCP tests** - `238ffacf` (feat)

**Plan metadata:** `67ff95af` (docs: complete plan)

## Files Created/Modified

- `server/mcp_tools/serializers.py` — `DetectChangesRequestSerializer` + snapshot entry
- `server/mcp_tools/views.py` — `DetectChangesView` (committed without concurrent charter WIP)
- `server/mcp_tools/urls.py` — `tools/detect_changes/`
- `server/tests/mcp_tools/test_schema_snapshot.py` — literal snapshot twin
- `server/tests/mcp_tools/test_detect_changes_tools.py` — PAT + success envelope green

## Decisions Made

- Safe-ref validation uses a serializers-local regex twin of `repo_mirror._SAFE_REF_RE` to avoid early import of the mirror subsystem
- Concurrent dirty `RouteRepositoriesView` / `aapply_charter_signal` WIP was preserved in the working tree and excluded from the Task 2 commit via HEAD+ours reconstruct
- DIFF-01 / DIFF-02 intentionally not marked Complete (hard constraint; shells incomplete until 123-04/05)

## Deviations from Plan

### Auto-fixed Issues

None - plan executed as written (import isort via ruff --fix only).

## Verification Results

Scoped (env prefix mandatory):

```text
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False
uv run pytest tests/mcp_tools/test_detect_changes_tools.py -k 'mcp_detect_changes' -q --reuse-db
→ 2 passed

uv run pytest tests/mcp_tools/test_schema_snapshot.py -q --reuse-db
→ 2 passed

uv run ruff check mcp_tools/serializers.py mcp_tools/views.py mcp_tools/urls.py \
  tests/mcp_tools/test_detect_changes_tools.py tests/mcp_tools/test_schema_snapshot.py
→ All checks passed
```

Note: plan verify command's `-k 'mcp_detect_changes'` deselects schema snapshot tests when both paths are listed; ran schema snapshot separately.

## Concurrent WIP Preservation

- After Task 2 commit, working-tree `server/mcp_tools/views.py` still contains `aapply_charter_signal` RouteRepositoriesView changes **and** `DetectChangesView`
- Commit `238ffacf` views.py hunks: only `DetectChangesRequestSerializer` import + `DetectChangesView` class (no charter blending)

## Known Stubs

- `test_conversational_detect_changes_registered` — skipped; owned by 123-04
- `test_two_surfaces_same_payload_detect_changes` — skipped; owned by 123-05

## Next Phase Readiness

- Ready for 123-04 conversational `@tool` shell (same `run_detect_changes` delegate)
- mcp/ submodule drift +1 accepted (D-27); alignment bookkeeping in 123-05

## Self-Check: PASSED

- FOUND: `DetectChangesRequestSerializer`, `DetectChangesView`, `tools/detect_changes/`, SUMMARY
- FOUND commits: `55924415`, `238ffacf`
- PRESERVED: concurrent `aapply_charter_signal` WIP in working-tree `views.py`
- CONFIRMED: commit `238ffacf` views.py hunks contain DetectChangesView only (no charter WIP)
