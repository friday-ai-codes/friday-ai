---
phase: 127-semgrep-lsp
plan: 03
subsystem: code_graph
tags: [semgrep-scan, queue-scan, durable, fail-open, worktree]

requires:
  - phase: 127-semgrep-lsp
    provides: SecurityFinding + SEMGREP_* settings + Fernet token + image SEMGREP_BIN (127-02)
provides:
  - "ensure_worktree_for_scan public worktree API"
  - "semgrep_scan CLI wrapper (scan + merge-base baseline + fail-open)"
  - "QUEUE_SCAN + scan-slot N=2 + durable_semgrep_scan"
  - "enqueue_semgrep_scan best-effort with initiated_by_user_id"
affects: [127-04]

tech-stack:
  added: []
  patterns:
    - "Semgrep via create_subprocess_exec argv list only; never import semgrep"
    - "--baseline-commit = git merge-base(target, source); fail-open error_code dict/dataclass"
    - "Independent QUEUE_SCAN + ConcurrencyWindow scan-slot (DEFAULT 2)"

key-files:
  created:
    - server/services/code_graph/semgrep_scan.py
    - server/services/code_graph/semgrep_enqueue.py
    - .planning/phases/127-semgrep-lsp/127-03-SUMMARY.md
  modified:
    - server/services/repo_mirror.py
    - server/durable/queues.py
    - server/durable/concurrency.py
    - server/durable/tasks.py
    - server/durable/tasks_impl.py
    - server/durable/handlers.py
    - server/tests/services/code_graph/test_semgrep_scan.py
    - server/tests/services/code_graph/test_semgrep_enqueue.py

key-decisions:
  - "SemgrepScanResult dataclass for structured fail-open outcomes (127-04 MR section)"
  - "tasks_impl.run_semgrep_scan never re-raises; returns error_code dict (D-04)"
  - "_maybe_patch_security_scan_section no-op hook reserved for 127-04"
  - "TAINT-01 marked for CLI/async/fail-open kernel; MR advisory copy remains 127-04"

patterns-established:
  - "Public ensure_worktree_for_scan wraps private _ensure_worktree (D-02)"
  - "enqueue_semgrep_scan mirrors charter/process best-effort defer + slot lock"

requirements-completed: [TAINT-01]

duration: 5min
completed: 2026-08-10
---

# Phase 127 Plan 03: Semgrep Scan + QUEUE_SCAN Summary

**Diff-aware Semgrep CLI wrapper with merge-base baseline, public worktree API, independent QUEUE_SCAN (N=2), and fail-open durable enqueue — never imports semgrep**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-08-09T22:20:48Z
- **Completed:** 2026-08-09T22:25:10Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Exposed `ensure_worktree_for_scan` and landed `semgrep_scan` (`scan` + `--baseline-commit` = merge-base, packs from `SEMGREP_CONFIGS`, Pro token env inject, `SecurityFinding` persist with redaction)
- Added `QUEUE_SCAN` / `scan_slot_lock` / `ascan_lock` (default concurrency 2) plus `durable_semgrep_scan` task/handler and `enqueue_semgrep_scan` best-effort helper
- Fail-open contract: timeout / mirror / CLI → stable `error_code`; enqueue failure returns `None` without raising
- Wave 0 scan + enqueue acceptance tests unskipped and green (7 tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: worktree 公共 API + semgrep_scan CLI** - `f2099230` (test RED) + `217eac88` (feat GREEN)
2. **Task 2: QUEUE_SCAN + durable_semgrep_scan + enqueue** - `a67c0de4` (test RED) + `7df63776` (feat GREEN)

**Plan metadata:** *(pending docs commit)*

## Files Created/Modified

- `server/services/repo_mirror.py` — `ensure_worktree_for_scan`
- `server/services/code_graph/semgrep_scan.py` — CLI argv/build, merge-base, persist, fail-open `SemgrepScanResult`
- `server/services/code_graph/semgrep_enqueue.py` — `enqueue_semgrep_scan`
- `server/durable/queues.py` — `QUEUE_SCAN` in `ALL_QUEUES`
- `server/durable/concurrency.py` — `DEFAULT_SCAN_CONCURRENCY` / `scan_slot_lock` / `ascan_lock`
- `server/durable/tasks.py` / `tasks_impl.py` / `handlers.py` — `durable_semgrep_scan` + fail-open job body + in-process adapter
- `server/tests/services/code_graph/test_semgrep_scan.py` / `test_semgrep_enqueue.py` — acceptance

## Decisions Made

- Return `SemgrepScanResult` from the service layer (attribute access for tests / 127-04) while durable job normalizes to a dict
- Job body never re-raises on scan failure; MR patch is a named no-op hook for 127-04
- Marked `TAINT-01` complete for the measurable CLI/async/fail-open kernel; advisory MR section copy stays in 127-04

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Parallel executor race on durable/test files**
- **Found during:** Task 1–2
- **Issue:** Concurrent agent wrote overlapping RED/GREEN commits for the same plan; working tree briefly held duplicate `ascan_lock` / mixed charter WIP
- **Fix:** Kept the landed atomic commits; restored concurrent charter WIP as unstaged; verified scoped pytest still green
- **Files modified:** none committed beyond plan intents
- **Verification:** 7/7 scan+enqueue tests pass
- **Committed in:** n/a (coordination only)

---

**Total deviations:** 1 auto-fixed (blocking/coordination)
**Impact on plan:** No scope creep; plan artifacts and tests match acceptance criteria.

## Issues Encountered

- Concurrent charter WIP touches the same durable modules; SCAN commits staged only QUEUE_SCAN paths; charter remains unstaged in WC
- `gsd-tools` not on PATH — used `node .cursor/gsd-core/bin/gsd-tools.cjs`

## User Setup Required

None beyond 127-02 image rebuild for `/opt/semgrep`. Optional Pro token via `set_semgrep_app_token`.

## Next Phase Readiness

- 127-04 can call `enqueue_semgrep_scan` / consume `SemgrepScanResult` and implement `_maybe_patch_security_scan_section` + `## 安全扫描` dual-link append
- Freeze surfaces (`repo_router_v2.py`, `mcp/`) untouched

## Threat Flags

None beyond plan register — subprocess argv list + token redaction + fail-open timeout cover T-127-01..03.

## Self-Check: PASSED

- [x] `server/services/code_graph/semgrep_scan.py` exists
- [x] `server/services/code_graph/semgrep_enqueue.py` exists
- [x] Commits `f2099230`, `217eac88`, `a67c0de4`, `7df63776` present
- [x] Acceptance rg + pytest (7 passed)
