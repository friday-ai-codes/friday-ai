---
phase: 127-semgrep-lsp
plan: 01
subsystem: testing
tags: [semgrep, lsp, wave0, frozen-surface, nyquist, pytest]

requires:
  - phase: 127-semgrep-lsp
    provides: CONTEXT/RESEARCH/PATTERNS/VALIDATION + five plan IDs
provides:
  - Wave 0 pytest acceptance stubs (skip) for TAINT-01/02/03 and LSP-01
  - Live D-12 LSP defaults + D-18 frozen-surface guards
  - Fake Semgrep JSON fixture
  - VALIDATION Per-Task Map aligned to 127-01..05 only
affects: [127-02, 127-03, 127-04, 127-05]

tech-stack:
  added: []
  patterns:
    - "Wave 0 skip stubs with pytest.fail + plan-tagged skip reason"
    - "Frozen-surface AST guards skip missing production modules via path.is_file()"

key-files:
  created:
    - server/tests/services/code_graph/test_semgrep_scan.py
    - server/tests/services/code_graph/test_security_scan_report.py
    - server/tests/services/code_graph/test_semgrep_enqueue.py
    - server/tests/services/code_graph/test_semgrep_app_token.py
    - server/tests/codegraph/test_security_finding_model.py
    - server/codegraph/lsp/tests/test_orphan_reap.py
    - server/tests/codegraph/test_lsp_defaults_unchanged.py
    - server/tests/services/code_graph/test_frozen_surface_127.py
    - server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py
    - server/tests/codegraph/test_revisit_impact03.py
    - server/tests/workflows/test_coding_security_scan.py
    - server/tests/mcp_tools/test_mr_security_scan.py
    - server/tests/fixtures/semgrep/sample_findings.json
    - .planning/phases/127-semgrep-lsp/127-01-SUMMARY.md
  modified:
    - .planning/phases/127-semgrep-lsp/127-VALIDATION.md

key-decisions:
  - "Wave 0 stubs skip until 127-02..05; frozen-surface + LSP defaults assert live"
  - "VALIDATION map is exactly five plans (127-01..05); no 127-06 row"
  - "Semgrep stays CLI-only — fixture/tests never imply uv.lock dependency"

patterns-established:
  - "Phase 127 frozen guard lists semgrep_scan/security_scan_report/semgrep_enqueue/orphan_reap"
  - "sample_findings.json uses check_id + extra.severity + fingerprint + nosemgrep note"

requirements-completed: []

duration: 2min
completed: 2026-08-10
---

# Phase 127 Plan 01: Wave 0 Acceptance Stubs Summary

**Nyquist Wave 0: 32 collectable Semgrep/LSP acceptance nodes + fixture + D-18 frozen-surface guards; VALIDATION map locked to five plan IDs**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-08-09T22:07:27Z
- **Completed:** 2026-08-09T22:09:00Z
- **Tasks:** 2
- **Files modified:** 14

## Accomplishments

- Landed skip-stub pytest nodes covering TAINT-01/02/03, LSP-01, and D-01..D-18 acceptance names for 127-02..05 to un-skip
- Live guards: `VOLAR`/`GOPLS` defaults False; AST/git freeze against `repo_router_v2` / `mcp/` / GraphService hot path
- Fake `sample_findings.json` with severity/fingerprint + nosemgrep documentation note
- Refreshed `127-VALIDATION.md` Per-Task Map to exactly `127-01`..`127-05` (Waves 0–4); no ghost `127-06`

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 验收测试桩 + Semgrep fixture** - `86a58c40` (test)
2. **Task 2: VALIDATION 与五 plan 编号对齐** - `da6e05d5` + follow-up `94784bf3` (docs)

**Plan metadata:** `b1e15ba6` (docs: complete plan; follow-up docs commit may amend VALIDATION sign-off)

## Files Created/Modified

- `server/tests/services/code_graph/test_semgrep_scan.py` — TAINT-01 CLI/fail-open stubs
- `server/tests/services/code_graph/test_security_scan_report.py` — TAINT-02/03 section stubs
- `server/tests/services/code_graph/test_semgrep_enqueue.py` — QUEUE_SCAN enqueue stubs
- `server/tests/services/code_graph/test_semgrep_app_token.py` — Fernet token stubs
- `server/tests/codegraph/test_security_finding_model.py` — SecurityFinding model stubs
- `server/codegraph/lsp/tests/test_orphan_reap.py` — orphan reap stubs
- `server/tests/codegraph/test_lsp_defaults_unchanged.py` — live defaults False assert
- `server/tests/services/code_graph/test_frozen_surface_127.py` — D-18 frozen-surface guards
- `server/tests/services/code_graph/test_dockerfile_semgrep_lsp_layers.py` — Dockerfile layer stubs
- `server/tests/codegraph/test_revisit_impact03.py` — IMPACT-03 revisit stubs
- `server/tests/workflows/test_coding_security_scan.py` — coding hang-point stubs
- `server/tests/mcp_tools/test_mr_security_scan.py` — MCP/mr_service hang-point stubs
- `server/tests/fixtures/semgrep/sample_findings.json` — fake Semgrep JSON
- `.planning/phases/127-semgrep-lsp/127-VALIDATION.md` — five-plan map + Wave 0 checklist

## Decisions Made

- Behavior stubs use `@pytest.mark.skip(reason="Wave 0 桩：由 127-0X 落地")` + `pytest.fail("Wave 0 桩")`; frozen-surface and LSP defaults run for real
- VALIDATION Sampling Rate distinguishes quick (per-task) vs full-for-wave / full-phase
- `nyquist_compliant: true` after Wave 0 files land; `wave_0_complete` flips true with this SUMMARY

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Do not mark TAINT/LSP requirements complete from Wave 0**
- **Found during:** Summary / state updates
- **Issue:** `requirements.mark-complete` would check off TAINT-01..03 / LSP-01 after stubs-only plan
- **Fix:** Keep REQUIREMENTS Pending; SUMMARY `requirements-completed: []`; STATE decision records the lock
- **Files modified:** `.planning/REQUIREMENTS.md` (left unchecked), `127-01-SUMMARY.md`, `.planning/STATE.md`
- **Verification:** REQUIREMENTS checkboxes remain `[ ]` for TAINT/LSP
- **Committed in:** docs complete commit

---

**Total deviations:** 1 auto-fixed (Rule 2)
**Impact on plan:** Prevents false requirement completion; no scope creep.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for 127-02 (Dockerfile / settings / SecurityFinding / token) to un-skip Wave 0 nodes owned by that plan
- Hard locks remain: no Semgrep in uv.lock; no touch `repo_router_v2.py` or `mcp/`

## Self-Check: PASSED

- FOUND: all 13 Wave 0 test/fixture paths + updated VALIDATION
- FOUND: `86a58c40` Task 1 commit
- FOUND: `da6e05d5` Task 2 commit
- Collect-only: 32 items; live guards: 4 passed

---
*Phase: 127-semgrep-lsp*
*Completed: 2026-08-10*
