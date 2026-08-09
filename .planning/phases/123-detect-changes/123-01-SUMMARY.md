---
phase: 123-detect-changes
plan: 01
subsystem: code-intelligence
tags: [detect_changes, diff_mirror, rename, formatting_only, DIFF-01, DIFF-02]

requires:
  - phase: 123-00
    provides: Wave 0 pytest stub node names for kernel + diff_mirror
  - phase: 122-impact-trace
    provides: pure-kernel discipline (zero ORM, sampling logs) from impact.py
provides:
  - DiffMirrorResult / diff_mirror / ensure_mirror_sha on repo_mirror
  - code_graph/detect_changes.py pure overlap kernel (parse/rename/formatting)
  - Green Wave 0 stubs for test_diff_mirror + test_detect_changes
affects: [123-02, 123-03, 123-04, 123-05]

tech-stack:
  added: []
  patterns:
    - "two-dot git diff --unified=0 --find-renames via _run_git; cap 16MiB MirrorError"
    - "sha pin fetch +{sha}:refs/friday/pin-{12} (never refs/heads/{sha})"
    - "detect_changes zero ORM; old-side hunk×Symbol overlap; rename single entry"

key-files:
  created:
    - server/services/code_graph/detect_changes.py
  modified:
    - server/services/repo_mirror.py
    - server/tests/services/test_diff_mirror.py
    - server/tests/services/code_graph/test_detect_changes.py

key-decisions:
  - "DETECT_CHANGES_MAX_DIFF_BYTES lives on repo_mirror next to max_output_bytes"
  - "Truncated diff raises MirrorError(diff_too_large) instead of silent truncate"
  - "Files absent from symbols_by_path (excl. pure adds) are skipped — exclusion is caller-owned"

patterns-established:
  - "Kernel import path: services.code_graph.detect_changes (not barrel __all__)"
  - "changeType closed enum + impact_seed flag on each affected symbol"

requirements-completed: []

duration: 3min
completed: 2026-08-09
---

# Phase 123 Plan 01: Diff Mirror + Overlap Kernel Summary

**Tree-to-tree `diff_mirror` (-U0/--find-renames, sha pin, 16MiB cap) plus zero-ORM `detect_changes` overlap kernel with single-entry rename and formatting_only seed gating.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-09T18:34:02Z
- **Completed:** 2026-08-09T18:37:14Z
- **Tasks:** 2 (TDD RED→GREEN each)
- **Files modified:** 4

## Accomplishments

- Landed `DiffMirrorResult` / `diff_mirror` / `ensure_mirror_sha` with two-dot argv and credential-scrubbed errors
- Landed `detect_changes.py`: parse, ranges_overlap, formatting_only, detect_affected_symbols (D-05..D-08/D-15)
- Turned Wave 0 stubs green: 5 mirror + 9 kernel tests (14/14 scoped suite)

## Task Commits

Each task was committed atomically (TDD):

1. **Task 1 RED: diff_mirror failing tests** - `ecf5f9d3` (test)
2. **Task 1 GREEN: diff_mirror + ensure_mirror_sha** - `829167f7` (feat)
3. **Task 2 RED: detect_changes failing tests** - `cfd9caf8` (test)
4. **Task 2 GREEN: detect_changes pure kernel** - `680617f4` (feat)

**Plan metadata:** see final docs commit after this SUMMARY

## Files Created/Modified

- `server/services/repo_mirror.py` — `DETECT_CHANGES_MAX_DIFF_BYTES`, `DiffMirrorResult`, `diff_mirror`, `ensure_mirror_sha`
- `server/services/code_graph/detect_changes.py` — pure overlap kernel (new)
- `server/tests/services/test_diff_mirror.py` — argv / rename fixture / pin / byte-cap
- `server/tests/services/code_graph/test_detect_changes.py` — overlap / rename / formatting / threshold / exclusion

## Decisions Made

- Byte-cap disposition uses dedicated `MirrorError.code=diff_too_large` (still accepted by test allow-list with `mirror_fetch_failed`)
- Exclusion: modifications with no symbols in `symbols_by_path` are omitted; pure-add file summaries still emit without forging uids
- Did not touch `code_graph/__init__.py` barrel, `mcp/` submodule, or `repo_router_v2.py`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Correctness] Did not mark DIFF-01/DIFF-02 complete**
- **Found during:** State/requirements updates after Task 2
- **Issue:** Plan frontmatter lists DIFF-01/DIFF-02, but full REQ text still needs orchestration (`run_detect_changes` + batch impact + compare/base_ref wiring in 123-02+)
- **Fix:** Left REQUIREMENTS unchecked; `requirements-completed: []` in this SUMMARY
- **Files modified:** none (intentional no-op)
- **Verification:** REQUIREMENTS.md still Pending for DIFF-01/02

**Total deviations:** 1 intentional no-op (requirements timing)
**Impact on plan:** No scope creep; kernel/mirror deliverables match plan acceptance criteria.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for 123-02 orchestration (`run_detect_changes`: ACL, mirror wiring, batch `run_impact`, staleness)
- Kernel + mirror helpers are import-stable for dual MCP/conversational shells

## Verification Results

```text
GALAXY_CACHE_WARM_ON_STARTUP=False GRAPH_BUILD_ORPHAN_RECONCILE_ON_STARTUP=False \
  uv run pytest tests/services/code_graph/test_detect_changes.py \
  tests/services/test_diff_mirror.py -q --reuse-db
→ 14 passed

ruff check services/repo_mirror.py services/code_graph/detect_changes.py \
  tests/services/test_diff_mirror.py tests/services/code_graph/test_detect_changes.py
→ All checks passed

AST: detect_changes.py has no django / codegraph.models imports
Barrel: no detect_changes export in code_graph/__init__.py
```

## TDD Gate Compliance

- RED commits present: `ecf5f9d3`, `cfd9caf8`
- GREEN commits present after each: `829167f7`, `680617f4`

## Known Stubs

None in this plan's deliverables. Orchestrator/MCP Wave 0 stubs remain skipped for 123-02..05.

## Self-Check: PASSED

- FOUND: `server/services/code_graph/detect_changes.py`
- FOUND: `123-01-SUMMARY.md`
- FOUND: commits `ecf5f9d3`, `829167f7`, `cfd9caf8`, `680617f4`
