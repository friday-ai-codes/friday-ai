---
phase: 124-coding-chain
plan: 01
subsystem: task-executor
tags: [detect_changes, knowledge_tools, system_prompt, DIFF-03, MCP, PAT, non-blocking]

requires:
  - phase: 124-coding-chain
    provides: Wave 0 test_detect_changes_prompt skip stubs (124-00)
  - phase: 123-detect-changes
    provides: server DetectChangesRequestSerializer + run_detect_changes MCP PAT surface
provides:
  - detect_changes as 11th KNOWLEDGE_TOOL_SCHEMAS entry (auto allowed_tools)
  - ClaudeRunner._detect_changes_guidance static non-blocking prompt helper
  - _get_system_prompt parts-join (openspec + detect_changes coexist)
affects: [124-02, 124-03, coding-container-agent]

tech-stack:
  added: []
  patterns:
    - "Knowledge whitelist grows by appending KNOWLEDGE_TOOL_SCHEMAS; knowledge_allowed_tools auto-derives"
    - "System prompt extensions use parts-join helpers (static Chinese, no external concat)"
    - "detect_changes guidance is advisory-only; runner commit/push untouched (D-04)"

key-files:
  created: []
  modified:
    - task/core/knowledge_tools.py
    - task/core/executor.py
    - task/tests/test_knowledge_tools.py
    - task/tests/test_detect_changes_prompt.py
    - task/tests/test_openspec_prompt.py
    - task/tests/test_claude_sdk_integration.py
    - task/tests/test_blueprint_context_tools_schema.py
    - task/tests/test_blueprint_context_wait.py

key-decisions:
  - "D-02: detect_changes schema required=[repository_id, compare]; optional base_ref/max_depth/min_confidence/include_low_confidence/limit"
  - "D-01: prompt inject only when knowledge_endpoint+user_token and task_mode in {plan,execute}"
  - "D-04: guidance text hard-codes non-blocking HIGH/CRITICAL / failure continue-delivery; runner.py untouched"
  - "openspec MagicMock fixtures pin knowledge_endpoint/user_token=None to preserve base-prompt zero regression"

patterns-established:
  - "TDD for knowledge count: bump EXPECTED_TOOL_NAMES + all ==N assertions in one RED commit before schema GREEN"
  - "_detect_changes_guidance mirrors _openspec_guidance (independent static helper + conditional append)"

requirements-completed: [DIFF-03]

duration: 2min
completed: 2026-08-09
---

# Phase 124 Plan 01: Container detect_changes Whitelist + Prompt Summary

**Coding containers expose `mcp__friday-knowledge__detect_changes` via the 11th knowledge schema, and plan/execute system prompts append static non-blocking self-check guidance (DIFF-03 / D-01..D-04).**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-09T19:35:04Z
- **Completed:** 2026-08-09T19:37:00Z
- **Tasks:** 2 (each with RED+GREEN TDD commits)
- **Files modified:** 8

## Accomplishments

- Appended `detect_changes` to `KNOWLEDGE_TOOL_SCHEMAS` (required `repository_id`/`compare`; serializer-aligned optionals)
- Bumped all hard-coded knowledge tool count assertions 10→11 across task test surfaces
- Added `_detect_changes_guidance` + parts-join `_get_system_prompt` (openspec + detect_changes coexist)
- Unskipped Wave 0 `test_detect_changes_prompt.py`; pinned openspec fixtures against false knowledge mount
- Confirmed `task/core/runner.py` has zero `detect_changes` references (D-04 / D-16)

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: whitelist count assertions** - `c0a6bfa8` (test)
2. **Task 1 GREEN: detect_changes schema** - `c643ae3e` (feat)
3. **Task 2 RED: unskip prompt assertions** - `4a84d79f` (test)
4. **Task 2 GREEN: prompt guidance helper** - `ce2ecda4` (feat)

**Plan metadata:** _(pending docs commit)_

## Files Created/Modified

- `task/core/knowledge_tools.py` — 11th schema entry + comment count updates
- `task/core/executor.py` — `_detect_changes_guidance` + parts-join `_get_system_prompt`
- `task/tests/test_knowledge_tools.py` — EXPECTED + schema shape for detect_changes
- `task/tests/test_detect_changes_prompt.py` — Wave 0 stubs → green behavior tests
- `task/tests/test_openspec_prompt.py` — knowledge fields pinned for zero regression
- `task/tests/test_claude_sdk_integration.py` / `test_blueprint_context_tools_schema.py` / `test_blueprint_context_wait.py` — count 11

## Decisions Made

- Followed D-01..D-04 exactly: whitelist + advisory prompt only; no runner hard gate
- Schema description tells agent to self-check before ending turn; failures/quota → continue delivery, no retry spam
- explore / missing knowledge config skips guidance append

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- DIFF-03 container surface ready for 124-02/03 MR impact_report consumption
- Server `run_detect_changes` unchanged; MCP PAT path remains fail-closed on server
- Ready for Wave 1 plan 124-02 (shared impact_report formatter)

## TDD Gate Compliance

- RED commits present: `c0a6bfa8`, `4a84d79f`
- GREEN commits present after RED: `c643ae3e`, `ce2ecda4`

## Self-Check: PASSED

- All 8 key files found on disk
- Commits present: `c0a6bfa8`, `c643ae3e`, `4a84d79f`, `ce2ecda4`

---
*Phase: 124-coding-chain*
*Completed: 2026-08-09*
