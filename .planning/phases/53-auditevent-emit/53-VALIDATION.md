---
phase: 53
slug: auditevent-emit
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-17
---

# Phase 53 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-django, pytest-asyncio, pytest-socket) |
| **Config file** | `server/pyproject.toml` ([tool.pytest.ini_options]) |
| **Quick run command** | `cd server && uv run pytest tests/audit/ -q` |
| **Full suite command** | `cd server && uv run pytest -q` |
| **Estimated runtime** | ~quick <30s, full several min |

---

## Sampling Rate

- **After every task commit:** Run `cd server && uv run pytest tests/audit/ -q`
- **After every plan wave:** Run `cd server && uv run pytest -q`
- **Before `$gsd-verify-work`:** Full suite must be green + `uv run python manage.py makemigrations --check`
- **Max feedback latency:** ~30 seconds (quick)

---

## Per-Task Verification Map

> Filled concretely by the planner per task. Coverage targets below map success criteria → tests.

| SC | Requirement | Secure Behavior | Test Type | Automated Command |
|----|-------------|-----------------|-----------|-------------------|
| SC-1 model+single-entry | AUDIT-01 | `AuditEvent` row persists all fields; writes only via AuditService | unit | `uv run pytest tests/audit/test_audit_model.py tests/audit/test_audit_service.py -q` |
| SC-2 append-only | AUDIT-01 | model `save()` rejects update, `delete()` rejected; INV-6 grep guard finds no bypass writers | unit | `uv run pytest tests/audit/test_audit_append_only.py tests/audit/test_audit_inv6_guard.py -q` |
| SC-3 fail-soft emit | AUDIT-02 | emit failure swallowed + warning logged, main op not blocked; sync + async surface | unit | `uv run pytest tests/audit/test_audit_failsoft.py -q` |
| SC-4 redaction | AUDIT-02 | token/secret/password/api_key keys + high-entropy values redacted in before/after, never plaintext | unit | `uv run pytest tests/audit/test_audit_redaction.py -q` |
| migrations clean | — | `makemigrations --check` exits 0 | command | `cd server && uv run python manage.py makemigrations --check` |

---

## Wave 0 Requirements

- [ ] `server/tests/audit/__init__.py` + `conftest.py` if needed — shared fixtures (actor user, sample before/after dicts)
- [ ] Existing pytest infrastructure covers framework needs (no new framework install)

*Existing infrastructure (pytest-django) covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none) | — | All phase behaviors (model, service, append-only, fail-soft, redaction) are unit-testable | — |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
