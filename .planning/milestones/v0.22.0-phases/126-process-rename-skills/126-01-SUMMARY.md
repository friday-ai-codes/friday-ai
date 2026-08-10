---
phase: 126-process-rename-skills
plan: 01
subsystem: testing
tags: [process-trace, rename-preview, skills, wave0, nyquist, frozen-surface]

requires:
  - phase: 125-community-module-summary
    provides: SymbolCommunity + QUEUE_GRAPH enqueue patterns; frozen_surface_125 AST guard shape
provides:
  - Wave 0 Nyquist stubs for ProcessTrace / BFS / enqueue / affected_processes / process_query / rename_preview / D-16 frozen
  - 126-VALIDATION.md locked to plan IDs 126-01..05 (no ghost sixth plan)
affects:
  - 126-02 process BFS + durable enqueue (unskip model/trace/enqueue stubs)
  - 126-03 query + affected_processes + impact_report
  - 126-04 rename_preview
  - 126-05 skills injection

tech-stack:
  added: []
  patterns:
    - "Wave 0 skip stubs with pytest.mark.skip + pytest.fail placeholder"
    - "Live AST frozen-surface guards (path.is_file continue until kernels land)"

key-files:
  created:
    - server/tests/codegraph/test_process_trace_model.py
    - server/tests/services/code_graph/test_process_trace.py
    - server/tests/services/code_graph/test_process_enqueue.py
    - server/tests/services/code_graph/test_affected_processes.py
    - server/tests/services/code_graph/test_process_query.py
    - server/tests/services/code_graph/test_rename_preview.py
    - server/tests/services/code_graph/test_frozen_surface_126.py
  modified:
    - .planning/phases/126-process-rename-skills/126-VALIDATION.md

key-decisions:
  - "Wave 0 stubs skip until 126-02..05; frozen_surface_126 runs live AST/git guards immediately"
  - "VALIDATION Map locked to five plans 126-01..05 + 126-XX-F cross-ref; no 126-06 row or '| 126-06' marker"
  - "Production code untouched; D-16 frozen surfaces (repo_router_v2.py, mcp/) not staged"

patterns-established:
  - "Phase 126 freeze list: process_trace.py / rename_preview.py / process_enqueue.py must not import repo_router_v2"
  - "Nyquist node names registered before production kernels"

requirements-completed: [EXEC-01, EXEC-02, EXEC-03, RENAME-01, SKILL-01]

duration: 8min
completed: 2026-08-10
---

# Phase 126 Plan 01: Wave 0 Nyquist Stubs Summary

**Registered all Phase 126 automated acceptance nodes as collectable skip stubs and locked VALIDATION to plans 126-01..05 (no ghost sixth plan), with live D-16 frozen-surface guards.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-08-09T21:04:19Z
- **Completed:** 2026-08-09T21:12:00Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments

- Seven Wave 0 test files collect 26 nodes covering ProcessTrace schema, BFS hard gates, QUEUE_GRAPH process lock, affected_processes dialect, list/get call-through, rename_preview read-only safety, and D-16 freeze
- `test_frozen_surface_126.py` implements real AST/git assertions (not skipped); kernels absent → path continue
- `126-VALIDATION.md` Per-Task Map waves 0–4 align with plan frontmatter; `wave_0_complete: true` after this SUMMARY

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 验收测试桩（七文件）** - `1f805d9d` (test)
2. **Task 2: VALIDATION 与五 plan 编号对齐** - `fadaf910` (docs) + `e9e2a5d3` (fix prose scrub for Nyquist assert)

**Plan metadata:** `b5a6e56c` (docs: complete plan) + `19ef9ea6` (docs: STATE/ROADMAP)

## Files Created/Modified

- `server/tests/codegraph/test_process_trace_model.py` — ProcessTrace schema stubs (D-01/D-04)
- `server/tests/services/code_graph/test_process_trace.py` — BFS + community class stubs (D-02/D-05)
- `server/tests/services/code_graph/test_process_enqueue.py` — QUEUE_GRAPH / process lock stubs (D-03)
- `server/tests/services/code_graph/test_affected_processes.py` — assemble dialect stubs (D-07)
- `server/tests/services/code_graph/test_process_query.py` — list/get + MCP/agents call-through stubs (D-06)
- `server/tests/services/code_graph/test_rename_preview.py` — applied=false / dual-source / exclusion stubs (D-09..11)
- `server/tests/services/code_graph/test_frozen_surface_126.py` — live D-16 AST/git guards
- `.planning/phases/126-process-rename-skills/126-VALIDATION.md` — five-plan Map + Wave 0 checklist

## Decisions Made

- Stub bodies use `@pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")` + `pytest.fail("Wave 0 桩")` so collect-only works and later plans unskip
- Frozen guard mirrors Phase 125 shape; production kernels not yet present so file-missing is non-fatal
- VALIDATION prose avoids literal `| 126-06` so automated assert stays green while documenting the five-plan lock

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] VALIDATION prose broke `| 126-06` absence assert**
- **Found during:** Task 2 verify
- **Issue:** Plan lock sentence contained substring `| 126-06`, failing `assert '| 126-06' not in t`
- **Fix:** Reworded lock notes without that marker substring
- **Files modified:** `126-VALIDATION.md`
- **Commit:** `e9e2a5d3`

**2. [Rule 2 - Correctness] Skipped `requirements.mark-complete` for Wave 0**
- **Found during:** State updates after SUMMARY
- **Issue:** Frontmatter lists EXEC/RENAME/SKILL IDs, but 126-01 only registers Nyquist stubs — marking complete would falsely close product requirements
- **Fix:** Left REQUIREMENTS.md unchecked; implementing plans 126-02..05 own completion
- **Files modified:** none (intentional no-op)

## Auth Gates

None.

## Known Stubs

Intentional Wave 0 stubs (skip until later plans):

| File | Nodes | Reason |
|------|-------|--------|
| `test_process_trace_model.py` | 3 | Unskip in 126-02 |
| `test_process_trace.py` | 5 | Unskip in 126-02 |
| `test_process_enqueue.py` | 3 | Unskip in 126-02 |
| `test_affected_processes.py` | 4 | Unskip in 126-03 |
| `test_process_query.py` | 3 | Unskip in 126-03 |
| `test_rename_preview.py` | 6 | Unskip in 126-04 |

`test_frozen_surface_126.py` is **not** a stub — live assertions already green.

## Threat Flags

None — no new production endpoints, auth paths, or schema changes in this plan (test/docs only).

## Self-Check: PASSED

- FOUND: all seven test files + `126-VALIDATION.md`
- FOUND: commits `1f805d9d`, `fadaf910`, `e9e2a5d3`
- Frozen surfaces (`repo_router_v2.py`, `mcp/`) not in any 126-01 commit

## Next Phase Readiness

- Ready for 126-02 to implement ProcessTrace + BFS + enqueue and unskip Wave 0 stubs in those three files
- Do not stage concurrent WIP or frozen surfaces
