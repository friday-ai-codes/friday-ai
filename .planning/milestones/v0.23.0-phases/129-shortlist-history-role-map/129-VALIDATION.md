---
phase: 129
slug: shortlist-history-role-map
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-14
---

# Phase 129 — Validation Strategy

> Per-phase validation contract. Derived from `129-RESEARCH.md` ## Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django / pytest-asyncio) |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/services/process_runtime/test_shortlist.py tests/services/process_runtime/test_history_prior.py tests/services/process_runtime/test_role_map.py -q --tb=short` |
| **Full suite command** | `cd server && uv run pytest tests/services/process_runtime/test_shortlist.py tests/services/process_runtime/test_history_prior.py tests/services/process_runtime/test_role_map.py tests/services/process_runtime/test_funnel_shortlist.py tests/services/process_runtime/test_funnel_team_gate.py -q --tb=short --reuse-db` |
| **Estimated runtime** | ~30–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run that task's `<automated>` command
- **After every plan wave:** Run Full suite command above
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Automated Command | File Exists |
|----------|------|------|-------------|-------------------|-------------|
| 129-01-T1 | 01 | 1 | LIST-01/02/04 | `pytest .../test_shortlist.py` | after T1 |
| 129-01-T2 | 01 | 1 | LIST-01/02/04 | same | yes |
| 129-02-T1 | 02 | 1 | LIST-03 | `pytest .../test_history_prior.py` | after T1 |
| 129-02-T2 | 02 | 1 | LIST-03 | same + breakdown | yes |
| 129-03-T1 | 03 | 1 | ROLE-01/02/03 | `pytest .../test_role_map.py` | after T1 |
| 129-03-T2 | 03 | 1 | ROLE-01/02/03 | same | yes |
| 129-04-T1 | 04 | 2 | LIST+ROLE | `pytest .../test_funnel_shortlist.py` | after T1 |
| 129-04-T2 | 04 | 2 | LIST+ROLE | Full suite | yes |

---

## Wave 0

Existing pytest infra sufficient — no new fixtures scaffold required beyond plan RED tasks creating test files.
