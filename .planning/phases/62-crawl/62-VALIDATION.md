---
phase: 62
slug: crawl
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-20
---

# Phase 62 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend framework** | pytest 9.x (pytest-django + pytest-asyncio) |
| **Frontend framework** | vitest 4 + @vue/test-utils + happy-dom |
| **Backend quick run** | `cd server && uv run pytest tests/durable tests/delivery -q` |
| **Frontend quick run** | `cd web && pnpm vitest run src/components/knowledge` |
| **Full backend** | `cd server && uv run pytest -q` |
| **Estimated runtime** | ~1min backend quick / ~30s frontend |

---

## Sampling Rate

- **After every task commit:** run the touched-area quick command.
- **After every plan wave:** run backend quick + frontend quick.
- **Max feedback latency:** ~60 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 62-* run_crawl_ingest durable task + IngestRun status/columns | 01 | 1 | CRAWL-01 | unit | `uv run pytest tests/delivery -q` | ⬜ pending |
| 62-* enqueue/list/detail/start/stop/retry action endpoints | 01/02 | 1/2 | CRAWL-01 | integration | delivery api tests | ⬜ pending |
| 62-* at-least-once idempotent ingest (duplicate exec) | 01 | 1 | CRAWL-01 | unit | duplicate-dispatch guard | ⬜ pending |
| 62-* BatchIngestPanel backend-restored list + start/stop/retry (no in-memory batchId) | 03 | 2 | CRAWL-02 | frontend | vitest panel spec (zh-CN guard) | ⬜ pending |
| 62-* run_page_index real generation + target-hash skip | 02 | 2 | PAGEIDX-01 | unit | page_index hash-skip guard | ⬜ pending |
| 62-* tree_views.py bare background_runner → durable defer | 02 | 2 | PAGEIDX-01 | unit | grep + defer test | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Reuse `server/tests/durable/` + `server/tests/delivery/` fixtures; add crawl-ingest + page_index modules.
- [ ] Frontend: reuse existing `web/src/components/knowledge/__tests__` patterns (if present) / vitest setup.

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real restart resume: paste links → enqueue → `docker compose up -d` / Pod rebuild → task survives + auto-resumes | CRAWL-01 | Needs real Postgres + container restart | On a Postgres deploy, enqueue a crawl batch, restart the worker/web containers, confirm the queue list restores from DB and the durable job resumes |

*DB-truth-source restore IS automated under SQLite/postgres_queue (list endpoint reads IngestRun); only real container-restart resume is manual.*

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] nyquist_compliant: true set in frontmatter

**Approval:** approved 2026-06-20 (autonomous)
