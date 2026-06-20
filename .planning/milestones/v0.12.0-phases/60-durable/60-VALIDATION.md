---
phase: 60
slug: durable
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-20
---

# Phase 60 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-django + pytest-asyncio) |
| **Config file** | `server/pyproject.toml` [tool.pytest.ini_options] |
| **Quick run command** | `cd server && uv run pytest tests/durable -q` |
| **Full suite command** | `cd server && uv run pytest -q` (SQLite default; `postgres_queue` marker excluded by default addopts) |
| **Postgres suite command** | `cd server && DATABASE_URL=postgres://... uv run pytest -m postgres_queue -q` |
| **Estimated runtime** | ~30s quick / ~5min full |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/durable -q`
- **After every plan wave:** Run `cd server && uv run pytest -q`
- **Before verify-work:** Full SQLite suite green; Postgres `postgres_queue` suite green (CI)
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 60-01-* | 01 | 1 | DURABLE-01 | — | fallback executor never reaches Postgres; defer/get/cancel work in-process | unit | `uv run pytest tests/durable/test_service_fallback.py -q` | ❌ W0 | ⬜ pending |
| 60-01-* | 01 | 1 | DURABLE-01 | — | business code never imports procrastinate (grep guard) | unit | `uv run pytest tests/durable/test_no_direct_import.py -q` | ❌ W0 | ⬜ pending |
| 60-02-* | 02 | 2 | DURABLE-02 | — | worker/migrate role skips web-only reconcile/sweep | unit | `uv run pytest tests/durable/test_process_role.py -q` | ❌ W0 | ⬜ pending |
| 60-03-* | 03 | 2 | DURABLE-01, DURABLE-03 | — | Procrastinate backend defer/priority/retry/stalled rescue + queueing_lock singleton | integration (postgres_queue) | `uv run pytest -m postgres_queue -q` | ❌ W0 | ⬜ pending |
| 60-04-* | 04 | 3 | DURABLE-04 | — | Postgres CI job green; SQLite default path unaffected | manual/CI | GH Actions run | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/durable/conftest.py` — shared fixtures (durable service factory, fake procrastinate app, postgres marker fixtures)
- [ ] `server/tests/durable/__init__.py`
- [ ] `procrastinate[django]>=3.8.1,<3.9` added to `server/pyproject.toml` (uv add)
- [ ] `postgres_queue` marker registered in `server/pyproject.toml` + default addopts excludes it
- [ ] pytest-socket allowance for 127.0.0.1 under postgres_queue marker

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real kill-worker → other worker rescues in-flight stalled job | DURABLE-03 | Requires two live worker processes + real Postgres; expensive/flaky in CI | Start 2 workers against Postgres, defer long task, `kill -9` the holder, observe other worker re-runs via periodic rescue (human_needed) |

*Forged-heartbeat rescue (direct `get_stalled_jobs`/`retry_job`) IS automated under `postgres_queue`; only the real kill-worker E2E is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (revision 2026-06-20 — sign-off items 8a–8d met; Per-Task wave column reconciled to PLAN frontmatter 60-01:1 / 60-02:2 / 60-03:2 / 60-04:3)
