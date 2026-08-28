---
phase: 141
slug: capture
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-28
---

# Phase 141 — Validation Strategy

> Capture 账本与仓库挂钩的持续验证契约。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 + pytest-django |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `uv run pytest tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py -x` |
| **Full suite command** | `uv run pytest tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py tests/initiatives/test_memory_inv6_guard.py tests/initiatives/test_memory_service.py tests/mcp_tools/test_report_project_knowledge.py -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run the narrow test file(s) changed by that task.
- **After every plan wave:** Run all three Capture test modules.
- **Before `$gsd-verify-work`:** Capture tests and existing project-memory/MCP regression tests must be green.
- **Max feedback latency:** 30 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 141-01-01 | 01 | 0 | STORE-01, STORE-02, STORE-04, STORE-05 | T-141-01 | Behavior contracts pinned as RED tests including four named Wave 0 cases | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py::test_missing_session_id_uses_unspecified tests/initiatives/test_capture_service.py::test_repo_ambiguous_does_not_bind_fk tests/initiatives/test_capture_service.py::test_project_only_without_repo tests/initiatives/test_capture_service.py::test_project_repo_mismatch_binds_repo_only tests/initiatives/test_capture_service.py -x` | ❌ W0 | ⬜ pending |
| 141-01-02 | 01 | 0 | STORE-03, OBS-01, OBS-02 | T-141-02/05 | INV-6 + observability RED scaffolds | unit + static | `cd server && uv run pytest tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py -x` | ❌ W0 | ⬜ pending |
| 141-02-01 | 02 | 1 | STORE-01, STORE-02, STORE-05 | T-141-06 | Model/migration SET_NULL + unknown scalars | unit | `cd server && uv run python -c "from initiatives.models import SessionCapture"` | ❌ | ⬜ pending |
| 141-02-02 | 02 | 1 | STORE-03, OBS-02 | T-141-01/02 | Only CaptureService writes; input is redacted; missing session_id uses unspecified | unit + static | `cd server && uv run pytest tests/initiatives/test_capture_inv6_guard.py -x && uv run pytest tests/initiatives/test_capture_service.py -k "without_project_or_repo or unknown_scalars or redaction or actor or does_not_write_memory or missing_session_id_uses_unspecified" -x` | ❌ | ⬜ pending |
| 141-03-01 | 03 | 2 | STORE-04 | T-141-03 | Named linking cases plus authorized/unresolved/unauthorized still produce a row | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py::test_repo_ambiguous_does_not_bind_fk tests/initiatives/test_capture_service.py::test_project_only_without_repo tests/initiatives/test_capture_service.py::test_project_repo_mismatch_binds_repo_only -x && uv run pytest tests/initiatives/test_capture_service.py -k "link or unauthorized" -x` | ❌ | ⬜ pending |
| 141-03-02 | 03 | 2 | STORE-03 | T-141-04 | Duplicate user/session/question returns existing immutable capture; unspecified session_id still green | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py::test_idempotent_returns_existing tests/initiatives/test_capture_service.py::test_missing_session_id_uses_unspecified tests/initiatives/test_capture_service.py -x` | ❌ | ⬜ pending |
| 141-04-01 | 04 | 3 | OBS-01, OBS-02 | T-141-05 | caller lifecycle complete; logs contain no body/secrets | unit | `cd server && uv run pytest tests/initiatives/test_capture_observability.py -x` | ❌ | ⬜ pending |
| 141-04-02 | 04 | 3 | STORE-01 | T-141-11 | Capture separate from ProjectMemory/Ledger; report_project_knowledge unchanged | regression | `cd server && uv run pytest tests/initiatives/test_capture_service.py::test_persist_does_not_write_memory_or_ledger tests/mcp_tools/test_report_project_knowledge.py -x` | ❌ / ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/initiatives/test_capture_service.py` — persistence, linking, idempotency and separation tests.
- [ ] `server/tests/initiatives/test_capture_inv6_guard.py` — unique-writer and deferred-sink static guards.
- [ ] `server/tests/initiatives/test_capture_observability.py` — lifecycle, redaction and best-effort logging tests.
- [ ] RED `test_missing_session_id_uses_unspecified` — missing session_id persists as literal `unspecified` (D-06; Plan 02 greens).
- [ ] RED `test_repo_ambiguous_does_not_bind_fk` — normalized URL multi-match does not bind repository FK (Plan 03 greens).
- [ ] RED `test_project_only_without_repo` — authorized project without repo uses `project_only` (Plan 03 greens).
- [ ] RED `test_project_repo_mismatch_binds_repo_only` — project/repo mismatch binds repo only (Plan 03 greens).

---

## Manual-Only Verifications

All Phase 141 behaviors have automated verification. No frontend/UI checks.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verification or Wave 0 dependencies.
- [ ] Sampling continuity: no 3 consecutive tasks without automated verification.
- [ ] Wave 0 covers all missing references.
- [ ] No watch-mode flags.
- [ ] Feedback latency < 30s.
- [ ] `nyquist_compliant: true` set in frontmatter after Plan 04.

**Approval:** pending
