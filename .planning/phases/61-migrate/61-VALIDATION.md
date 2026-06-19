---
phase: 61
slug: migrate
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-20
---

# Phase 61 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-django + pytest-asyncio) |
| **Config file** | `server/pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `cd server && uv run pytest tests/durable tests/repositories -q` |
| **Full suite command** | `cd server && uv run pytest -q` |
| **Estimated runtime** | ~1min quick / ~5min full |

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched area.
- **After every plan wave:** Run the full SQLite suite.
- **Max feedback latency:** ~60 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 61-* migrate enqueue (5 points) | 01 | 1 | MIGRATE-01 | unit/integration | `uv run pytest tests/durable -q` | ⬜ pending |
| 61-* durable handlers + idempotency | 01/02 | 1/2 | IDEMP-01 | unit | duplicate-dispatch/duplicate-exec guard tests | ⬜ pending |
| 61-* one-time migration command | 02 | 2 | MIGRATE-02 | integration | migrate command idempotent re-run test | ⬜ pending |
| 61-* reconcile "no durable takeover" | 02 | 2 | MIGRATE-02 | unit | reconcile does not FAIL RUNNING with live durable job | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Reuse `server/tests/durable/` fixtures from Phase 60; add migration/idempotency test modules.

*Existing infrastructure (pytest-django) covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real upgrade migrating live in-flight resumable_tasks on Postgres | MIGRATE-02 | Needs real Postgres + pre-existing in-flight rows | Run migrate command against a Postgres deploy with PENDING/RUNNING index/graph resumable_tasks; confirm durable jobs created, old rows migrated, no double-run |

*Forged/seeded in-flight rows ARE automated under SQLite/postgres_queue; only real-deploy upgrade is manual.*

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] nyquist_compliant: true set in frontmatter

**Approval:** approved 2026-06-20 (autonomous)
