---
phase: 124-coding-chain
plan: 02
subsystem: code-graph
tags: [impact_report, detect_changes, DIFF-04, fail-soft, MR, observability]

requires:
  - phase: 124-coding-chain
    provides: Wave 0 test_impact_report skip stubs (124-00)
  - phase: 123-detect-changes
    provides: run_detect_changes orchestration envelope
provides:
  - Shared services.code_graph.impact_report module (build/append)
  - CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS / MAX_CHARS settings
  - Green test_impact_report.py covering stub/four-section/observability
affects: [124-03, workflow-MR, mcp-MR]

tech-stack:
  added: []
  patterns:
    - "Single formatter consumes run_detect_changes via asyncio.wait_for; shells must not re-render"
    - "Fail-soft stub with stable error_code; last-resort empty string like pr_cross_reference"
    - "initiated_by_user_id on every impact_report_* event (user.id or system)"

key-files:
  created:
    - server/services/code_graph/impact_report.py
  modified:
    - server/friday/settings.py
    - server/tests/services/code_graph/test_impact_report.py

key-decisions:
  - "D-05: build_impact_report_section is the sole render entry; reuses Phase 123 run_detect_changes"
  - "D-10/D-08: timeout 30.0s and max_chars 10240 via settings only — no kill-switch (D-13)"
  - "D-11: repository_not_indexed → not_indexed; TimeoutError → timeout; GraphAccessDenied/other → unavailable"
  - "T-124-02: log error text sanitized (redact + strip Traceback/absolute paths) beyond bare redact_secrets_in_text"

patterns-established:
  - "append_impact_report idempotent on ## 影响面 marker"
  - "user=None short-circuits before run_detect_changes with unavailable stub + initiated_by_user_id=system"

requirements-completed: []  # DIFF-04 shared core landed; MR dual-path wiring remains 124-03

duration: 3min
completed: 2026-08-09
---

# Phase 124 Plan 02: Shared impact_report Formatter Summary

**Shared `impact_report` module builds fail-soft `## 影响面` markdown (Changes/Affected/Risk/Recommendations) by consuming `run_detect_changes`, with timeout/volume settings and green Wave 0 tests (DIFF-04 core).**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-09T19:38:23Z
- **Completed:** 2026-08-09T19:41:28Z
- **Tasks:** 2 (Task 2 = RED + GREEN TDD)
- **Files modified:** 3

## Accomplishments

- Added `CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS` (30.0) and `CODE_GRAPH_IMPACT_REPORT_MAX_CHARS` (10240) next to CODE_GRAPH_* settings; no product kill-switch (D-13)
- Implemented `build_impact_report_section` / `append_impact_report` / `IMPACT_SECTION_MARKER` consuming `run_detect_changes` under `asyncio.wait_for`
- Fail-soft stubs for `ok=False` / timeout / ACL / missing user; partial success still renders four sections (D-12)
- Observability: static `impact_report_started|completed|failed` with `component=code_graph`, `category=caller`, `initiated_by_user_id`, `duration_ms`
- Unskipped Wave 0 `test_impact_report.py` — **10 passed**

## Task Commits

Each task was committed atomically:

1. **Task 1: settings 阈值** - `d979886f` (feat)
2. **Task 2 RED: failing formatter assertions** - `7679d9b4` (test)
3. **Task 2 GREEN: impact_report module** - `1db9d07f` (feat)

**Plan metadata:** `1e17ea43` (docs: complete plan)

## Files Created/Modified

- `server/services/code_graph/impact_report.py` — shared formatter + fail-soft + observability
- `server/friday/settings.py` — IMPACT_REPORT timeout/max_chars only (unrelated REPO_ROUTER WIP left unstaged)
- `server/tests/services/code_graph/test_impact_report.py` — Wave 0 stubs → green behavior tests

## Decisions Made

- Reused Phase 123 `run_detect_changes` exclusively; no BFS/diff rewrite
- Risk aggregation from `impacts[*].impact.risk_level` (uppercase display); empty → LOW; truncated/file_level_only → at least MEDIUM
- Recommendations use rule phrases only; no invented `affected_processes` Process narrative
- `settings.py` staged via index blob so concurrent `REPO_ROUTER_STAGE1_MAX_CANDIDATES` WIP stayed unstaged

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Sanitize Traceback/paths in failed-event error field**
- **Found during:** Task 2 GREEN (`test_stub_omits_stack_and_secrets`)
- **Issue:** `redact_secrets_in_text` alone left `Traceback` / absolute paths in `impact_report_failed` kv
- **Fix:** Added `_sanitize_error_text` (redact + strip Traceback + absolute-path scrub) before logging
- **Files modified:** `server/services/code_graph/impact_report.py`
- **Verification:** `test_impact_report.py` 10 passed
- **Committed in:** `1db9d07f` (part of Task 2 GREEN)

**2. [Rule 2 - Correctness] Keep DIFF-04 Pending until 124-03 MR wiring**
- **Found during:** state updates after SUMMARY
- **Issue:** Plan frontmatter lists `requirements: [DIFF-04]` but 124-03 also owns DIFF-04 (workflow/MCP append). Marking Complete after formatter-only would falsely close the REQ.
- **Fix:** Left DIFF-04 Pending in REQUIREMENTS.md; `requirements-completed: []` in this SUMMARY
- **Files modified:** `.planning/REQUIREMENTS.md`, `124-02-SUMMARY.md`

## Issues Encountered

None blocking. `gsd-tools` CLI not on PATH; state updates via `node .cursor/gsd-core/bin/gsd-tools.cjs`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Shared formatter ready for 124-03 workflow + MCP MR wiring (`append_impact_report` + `build_impact_report_section`)
- Dual-path parity sentinel still Wave 0 skip until 124-03
- Frozen surfaces untouched: `mcp/`, `repo_router_v2.py`, charter WIP

## TDD Gate Compliance

- RED commit present: `7679d9b4`
- GREEN commit present after RED: `1db9d07f`

## Self-Check: PASSED

- FOUND: `server/services/code_graph/impact_report.py`
- FOUND: `server/tests/services/code_graph/test_impact_report.py`
- FOUND commits: `d979886f`, `7679d9b4`, `1db9d07f`
- Scoped pytest: 10 passed / 0 failed / 0 skipped
- ruff check: clean on touched Python files
