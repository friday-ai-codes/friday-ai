---
phase: 127-semgrep-lsp
plan: 04
subsystem: code_graph
tags: [security-scan-report, mr-hangpoint, advisory, ce-disclaimer, pro-token, nosemgrep]

requires:
  - phase: 127-semgrep-lsp
    provides: enqueue_semgrep_scan + SemgrepScanResult + QUEUE_SCAN + maybe_patch hook (127-03)
provides:
  - "SECURITY_SECTION_MARKER ## 安全扫描 + append/build/stub helpers"
  - "Dual hang-points (coding / mr_service / MCP) via attach_security_scan_pending"
  - "Async MR description patch stub→results (pr_cross_reference paradigm)"
  - "CE function-local taint disclaimer + nosemgrep + Pro opt-in honesty"
affects: [127-05]

tech-stack:
  added: []
  patterns:
    - "MR section clone of impact_report: marker + idempotent append + fail-open stub"
    - "stub-then-async: pending stub at create; enqueue after MR id; patch replaces stub only"
    - "Advisory-only copy; CE/Pro honesty; redact token/stack/abs paths (T-127-01/05)"

key-files:
  created:
    - server/services/code_graph/security_scan_report.py
    - .planning/phases/127-semgrep-lsp/127-04-SUMMARY.md
  modified:
    - server/workflows/nodes/ai/coding.py
    - server/workflows/services/mr_service.py
    - server/mcp_tools/merge_request_service.py
    - server/durable/tasks_impl.py
    - server/tests/services/code_graph/test_security_scan_report.py
    - server/tests/workflows/test_coding_security_scan.py
    - server/tests/mcp_tools/test_mr_security_scan.py

key-decisions:
  - "Shared attach_security_scan_pending for stub; enqueue after create with mr_key=MR id (D-04)"
  - "patch_mr_security_scan_section in security_scan_report; tasks_impl maybe_patch thin wrapper"
  - "Pro line only when encrypted/env token present; never log or embed token (D-09)"
  - "No blocking whitelist / no MR comment path in this plan (Deferred)"

patterns-established:
  - "Dual-link shells catch security_scan_shell_failed; helper owns business logic (D-06)"
  - "replace_security_scan_section preserves ## 影响面 and other ## sections"

requirements-completed: [TAINT-02, TAINT-03]

duration: 5min
completed: 2026-08-10
---

# Phase 127 Plan 04: Security Scan MR Section Summary

**`## 安全扫描` MR section with advisory severity/CE/nosemgrep/Pro honesty, dual workflow+MCP hang-points, and stub→async patch — never blocks MR create**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-08-09T22:26:21Z
- **Completed:** 2026-08-09T22:30:43Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Landed `security_scan_report.py`: idempotent `## 安全扫描` append, severity findings, CE function-local disclaimer, `nosemgrep` note, Pro opt-in short line, redacted stubs
- Wired coding / `mr_service` / MCP create-MR seams to the same `attach_security_scan_pending` helper + post-create `enqueue_semgrep_scan`
- Implemented `maybe_patch_security_scan_section` → `patch_mr_security_scan_section` (GitHub `pr.edit` / GitLab `mr.save`, fail-soft, skip if already complete)
- Unskipped Wave 0 dual-link + report tests — **10 passed**

## Task Commits

Each task was committed atomically (TDD RED→GREEN):

1. **Task 1: security_scan_report helper** - `3b149299` (test RED; parallel `505f83c3` superseding draft) + `6f294939` (feat GREEN)
2. **Task 2: dual hang-points + async MR patch** - `9a45052d` (test RED) + `2a25631a` (feat GREEN)

**Plan metadata:** _(pending docs commit)_

## Files Created/Modified

- `server/services/code_graph/security_scan_report.py` — marker/append/build/stub/attach/patch helpers
- `server/workflows/nodes/ai/coding.py` — hang-point + post-create/dedup enqueue
- `server/workflows/services/mr_service.py` — hang-point + post-create enqueue
- `server/mcp_tools/merge_request_service.py` — hang-point + post-create enqueue
- `server/durable/tasks_impl.py` — `maybe_patch_security_scan_section` implementation
- `server/tests/services/code_graph/test_security_scan_report.py` — TAINT-02/03 contract
- `server/tests/workflows/test_coding_security_scan.py` — coding fail-open hang-point
- `server/tests/mcp_tools/test_mr_security_scan.py` — MCP + mr_service fail-open

## Decisions Made

- Create path writes `pending` stub only; enqueue after platform MR id exists (avoids race with async patch)
- Patch loads `SecurityFinding` by `mr_key`, builds full section with CE/Pro, replaces stub only
- Frozen surfaces untouched: `repo_router_v2.py`, `mcp/` submodule

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Parallel executor race on Task 1 RED/GREEN**
- **Found during:** Task 1
- **Issue:** Concurrent agent also wrote/committed `test_security_scan_report` RED + `security_scan_report` GREEN while this executor started
- **Fix:** Adopted landed commits (`3b149299`/`6f294939`); continued with Task 2 hang-points/patch
- **Files modified:** none beyond plan intents
- **Verification:** 6/6 report tests green
- **Committed in:** n/a (coordination)

**2. [Rule 2 - Correctness] Dedup reuse also enqueues scan**
- **Found during:** Task 2
- **Issue:** Coding path that reuses an existing open MR would skip enqueue if only hooked after `create_merge_request`
- **Fix:** Fire-and-forget `enqueue_semgrep_scan` on dedup reuse with `mr_key=existing.mr_id`
- **Files modified:** `server/workflows/nodes/ai/coding.py`
- **Verification:** coding hang-point tests green
- **Committed in:** `2a25631a`

---

**Total deviations:** 2 auto-fixed (1 blocking/coordination, 1 correctness)
**Impact on plan:** No scope creep; D-04/D-06..D-09 closed as planned.

## Issues Encountered

- Concurrent charter WIP in `tasks_impl.py` — SCAN/MR patch staged only plan paths; charter restored unstaged after commit
- `gsd-tools` not on PATH — used `node .cursor/gsd-core/bin/gsd-tools.cjs`

## User Setup Required

None beyond prior Semgrep image/token setup (127-02). Optional Pro: `set_semgrep_app_token`.

## Next Phase Readiness

- 127-05 can proceed (LSP orphan reap / IMPACT-03 revisit / defaults stay False)
- Freeze surfaces still untouched

## Threat Flags

None beyond plan register — advisory copy + redact + async enqueue cover T-127-01/02/05.

## Known Stubs

None that block the plan goal — create-path `pending` stub is intentional and replaced by async patch.

## Self-Check: PASSED

- [x] `server/services/code_graph/security_scan_report.py` exists with `SECURITY_SECTION_MARKER` / `append_security_scan` / `build_security_scan_section`
- [x] Hang-points contain `append_security_scan` + `enqueue_semgrep_scan` in coding / mr_service / MCP
- [x] Commits `3b149299`, `6f294939`, `9a45052d`, `2a25631a` present
- [x] Scoped pytest 10 passed
