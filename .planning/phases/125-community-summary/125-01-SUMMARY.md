---
phase: 125-community-summary
plan: 01
subsystem: testing
tags: [community, module-summary, call-source, observability, wave-0]

requires:
  - phase: observability / CallSource registry
    provides: LOGGING-SPEC §4.1 + CallSource enum dual-registration pattern
provides:
  - "CallSource.MODULE_SUMMARY / LOGGING-SPEC module_summary (45 值)"
  - "Seven Wave 0 skip-stub test files for MOD-01..04 acceptance nodes"
  - "125-VALIDATION Per-Task Map aligned to exactly four plans (125-01..04)"
affects:
  - 125-02 (unskip model/Louvain/enqueue stubs)
  - 125-03 (unskip module_summary + rebuild×2 LLM=0 stubs)
  - 125-04 (unskip signal/prompt/frozen-surface stubs)

tech-stack:
  added: []
  patterns:
    - "D-09: register call_source in LOGGING-SPEC + CallSource + guardian test BEFORE any LLM call site"
    - "Wave 0 Nyquist stubs: @pytest.mark.skip + pytest.fail(\"Wave 0 桩\") collectable node names"

key-files:
  created:
    - server/tests/services/code_graph/test_community.py
    - server/tests/services/code_graph/test_module_summary.py
    - server/tests/services/code_graph/test_community_enqueue.py
    - server/tests/services/code_graph/test_frozen_surface_125.py
    - server/tests/codegraph/test_symbol_community_model.py
    - server/tests/services/test_module_summary_signal.py
    - server/tests/services/process_runtime/test_module_summary_prompt.py
  modified:
    - .planning/observability/LOGGING-SPEC.md
    - server/agents/call_source.py
    - server/tests/test_model_usage_call_source.py
    - .planning/phases/125-community-summary/125-VALIDATION.md

key-decisions:
  - "D-09 dual registration completed before any MODULE_SUMMARY usage (Pitfall 3 avoided)"
  - "Wave 0 stubs use skip reason pointing to owning plan (125-02/03/04), not a fifth plan"
  - "Frozen surfaces repo_router_v2.py and mcp/ untouched in all commits"

patterns-established:
  - "call_source count: LOGGING-SPEC prose + CallSource docstring + _EXPECTED_CALL_SOURCES len must stay in lockstep (now 45)"
  - "Phase 125 validation map is exactly four rows; ghost 125-05 is forbidden"

requirements-completed: []  # Wave 0 scaffolding only; MOD-01..04 fulfilled by 125-02..04

duration: 2min
completed: 2026-08-09
---

# Phase 125 Plan 01: Wave 0 call_source + Acceptance Stubs Summary

**Registered `call_source=module_summary` (45 values) and collected 26 Wave 0 skip-stub nodes for community/module-summary acceptance**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-09T20:12:41Z
- **Completed:** 2026-08-09T20:14:30Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Dual-registered `module_summary` in LOGGING-SPEC §4.1 and `CallSource.MODULE_SUMMARY`; guardian test green at 45 values
- Added seven Wave 0 skip-stub test files covering Louvain/fingerprint/rebuild×2 LLM=0/enqueue/model/signal/prompt/frozen surface
- Aligned `125-VALIDATION.md` Per-Task Verification Map to exactly four plans (waves 0–3); set `wave_0_complete: true`

## Task Commits

Each task was committed atomically:

1. **Task 1: 登记 call_source=module_summary（先于一切调用点）** - `cb0f86a9` (feat)
2. **Task 2: Wave 0 验收测试桩 + VALIDATION 对齐** - `36a08aaf` (test)

**Plan metadata:** (docs commit after this SUMMARY)

## Files Created/Modified

- `.planning/observability/LOGGING-SPEC.md` — §4.1 `module_summary` row; 44→45
- `server/agents/call_source.py` — `MODULE_SUMMARY = "module_summary"`
- `server/tests/test_model_usage_call_source.py` — expected set + `len == 45`
- `server/tests/services/code_graph/test_community.py` — 8 Louvain/fingerprint/rebuild stubs
- `server/tests/services/code_graph/test_module_summary.py` — 4 LLM helper stubs
- `server/tests/services/code_graph/test_community_enqueue.py` — 3 enqueue/hook stubs
- `server/tests/services/code_graph/test_frozen_surface_125.py` — 2 D-13 frozen-surface stubs
- `server/tests/codegraph/test_symbol_community_model.py` — 3 model/soft-ref stubs
- `server/tests/services/test_module_summary_signal.py` — 3 signal stubs
- `server/tests/services/process_runtime/test_module_summary_prompt.py` — 3 prompt stubs
- `.planning/phases/125-community-summary/125-VALIDATION.md` — 4-row map + Wave 0 checklist

## Decisions Made

- Followed D-09 strictly: no `module_summary.py` or `use_call_source(MODULE_SUMMARY)` call sites in this plan
- Kept MOD-01..04 requirements unchecked in REQUIREMENTS.md — Wave 0 only scaffolds acceptance nodes
- Never staged `server/codegraph/services/repo_router_v2.py` or `mcp/`

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

Intentional Wave 0 stubs (skip + `pytest.fail("Wave 0 桩")`), to be unskipped by later plans:

| File | Nodes | Owning plan |
|------|-------|-------------|
| `test_community.py` | 8 | 125-02 / 125-03 |
| `test_module_summary.py` | 4 | 125-03 |
| `test_community_enqueue.py` | 3 | 125-02 |
| `test_symbol_community_model.py` | 3 | 125-02 |
| `test_module_summary_signal.py` | 3 | 125-04 |
| `test_module_summary_prompt.py` | 3 | 125-04 |
| `test_frozen_surface_125.py` | 2 | 125-04 |

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for 125-02: SymbolCommunity + Louvain/fingerprint + durable enqueue (unskip model/community/enqueue stubs)
- `CallSource.MODULE_SUMMARY` available for 125-03 LLM wiring
- Frozen-surface guard stubs collectable for 125-04 final green

## Self-Check: PASSED

- FOUND: `.planning/phases/125-community-summary/125-01-SUMMARY.md`
- FOUND: `server/agents/call_source.py` contains `MODULE_SUMMARY`
- FOUND: seven Wave 0 test stub files
- FOUND: commit `cb0f86a9`
- FOUND: commit `36a08aaf`
- CONFIRMED: neither commit contains `repo_router_v2.py` or `mcp/`

---
*Phase: 125-community-summary*
*Completed: 2026-08-09*
