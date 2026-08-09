---
phase: 124-coding-chain
plan: 03
subsystem: code-graph
tags: [impact_report, MR, DIFF-04, fail-soft, D-14, workflow, MCP]

requires:
  - phase: 124-coding-chain
    provides: Shared build_impact_report_section / append_impact_report (124-02)
  - phase: 124-coding-chain
    provides: Wave 0 dual-path test stubs (124-00)
provides:
  - AICodingNode._create_mr_for_repo fail-soft impact append (D-06 workflow)
  - MCP create_merge_request impact append + user ACL plumbing
  - mr_service.create_mr_for_task dialect elimination
  - D-14 workflow↔MCP parity sentinel green
  - 124-VALIDATION nyquist_compliant
affects: [phase-124-complete, DIFF-04]

tech-stack:
  added: []
  patterns:
    - "Outer try/except around build+append at every MR shell; helper already fail-soft"
    - "View/work_item only pass user=; never render ## 影响面 markdown in the shell"
    - "views.py concurrent WIP staged via git update-index --cacheinfo blob"

key-files:
  created: []
  modified:
    - server/workflows/nodes/ai/coding.py
    - server/workflows/services/mr_service.py
    - server/mcp_tools/merge_request_service.py
    - server/mcp_tools/views.py
    - server/mcp_tools/work_item_execution_service.py
    - server/tests/workflows/test_coding_impact_report.py
    - server/tests/mcp_tools/test_mr_impact_report.py
    - .planning/phases/124-coding-chain/124-VALIDATION.md

key-decisions:
  - "D-06: three MR shells (AICodingNode, MCP create_merge_request, create_mr_for_task) call the same helper"
  - "D-09: outer except pass guarantees impact never blocks create_merge_request"
  - "Draft stays sync; create path always appends (idempotent on ## 影响面 marker)"
  - "T-124-05: CreateMergeRequestView passes request.user; work_item passes initiating_user"

patterns-established:
  - "Index-blob staging for files with unrelated concurrent WIP (views.py charter left unstaged)"
  - "D-14 parity asserts shared_section.strip() appears in both final MR descriptions"

requirements-completed: [DIFF-04]

duration: 3min
completed: 2026-08-09
---

# Phase 124 Plan 03: MR Dual-Path Impact Wiring Summary

**Wired shared `build_impact_report_section` into AICodingNode, MCP `create_merge_request`, and `mr_service.create_mr_for_task` with fail-soft append and green D-14 parity (DIFF-04 / success criteria 2–3).**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-09T19:43:19Z
- **Completed:** 2026-08-09T19:46:29Z
- **Tasks:** 2 (each RED + GREEN TDD)
- **Files modified:** 8

## Accomplishments

- `AICodingNode._create_mr_for_repo` appends impact before `MRCreateRequest`; `_finalize_and_notify` passes `_resolve_dispatch_user`
- `mr_service.create_mr_for_task` uses the same helper (compare=branch, base_ref=target; user from `workflow_execution.triggered_by`)
- MCP `create_merge_request(..., user=)` appends after default description fill; idempotent when marker already present
- `CreateMergeRequestView` transmits `user=request.user` only; `work_item_execution_service` passes `user=initiating_user`
- Wave gate Quick run **18 passed**; `124-VALIDATION.md` → `nyquist_compliant: true` / Per-Task Status green

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: workflow impact assertions** - `230d14e6` (test)
2. **Task 1 GREEN: workflow + mr_service wiring** - `7baf8359` (feat)
3. **Task 2 RED: MCP parity assertions** - `d4a93651` (test)
4. **Task 2 GREEN: MCP wiring + VALIDATION** - `da97cfc0` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `server/workflows/nodes/ai/coding.py` — optional `user=` + fail-soft impact append
- `server/workflows/services/mr_service.py` — create_mr_for_task dialect elimination
- `server/mcp_tools/merge_request_service.py` — create_merge_request user + append
- `server/mcp_tools/views.py` — `user=request.user` only (charter WIP left unstaged)
- `server/mcp_tools/work_item_execution_service.py` — `user=initiating_user`
- `server/tests/workflows/test_coding_impact_report.py` — 4 green behavior tests
- `server/tests/mcp_tools/test_mr_impact_report.py` — 4 green incl. D-14 sentinel
- `.planning/phases/124-coding-chain/124-VALIDATION.md` — Nyquist sign-off

## Decisions Made

- Reused 124-02 helper exclusively; no BFS/render fork in shells
- Kept `_draft_from_summary` sync; create path always appends (marker idempotency covers draft→create)
- Did not wire CreatePRNode (deferred per plan)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Correctness] Stage views.py via index blob to preserve charter WIP**
- **Found during:** Task 2 GREEN commit
- **Issue:** `server/mcp_tools/views.py` had substantial unrelated charter RouteRepositories WIP; `git add` would poison the commit
- **Fix:** Built HEAD+Phase124 blob, `git update-index --cacheinfo 100644 <blob> server/mcp_tools/views.py`; working tree retains charter WIP (`MM` → post-commit ` M`)
- **Files modified:** `server/mcp_tools/views.py` (staged hunk only)
- **Verification:** `git show HEAD -- views.py` contains only `+user=request.user`; no `aapply_charter_signal`
- **Committed in:** `da97cfc0`

## Issues Encountered

None blocking. `gsd-tools` CLI not on PATH; state updates via `node .cursor/gsd-core/bin/gsd-tools.cjs`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- DIFF-04 dual-path wiring complete; Phase 124 success criteria 2/3 covered
- D-16 freeze held: no `mcp/` submodule edits, no `repo_router_v2.py` commits
- Concurrent charter WIP in `views.py` remains unstaged for the other session

## Self-Check: PASSED

- SUMMARY/artifacts/tests present on disk
- Commits `230d14e6` `7baf8359` `d4a93651` `da97cfc0` exist
- Quick run 18 passed; D-16 freeze: no mcp/ or repo_router_v2 in plan commits
- views.py: only `user=request.user` hunk committed; charter WIP left unstaged
