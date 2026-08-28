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
| **Full suite command** | `uv run pytest tests/initiatives/ tests/mcp_tools/test_report_project_knowledge.py -x` |
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
| 141-01-01 | 01 | 0 | STORE-01, STORE-02, STORE-05 | T-141-01 | Nullable links and unknown sentinels persist without guessing | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py -k "without_project_or_repo or unknown_scalars" -x` | ❌ W0 | ⬜ pending |
| 141-01-02 | 01 | 1 | STORE-03, OBS-02 | T-141-02 | Only CaptureService writes; input is redacted | unit + static | `cd server && uv run pytest tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_service.py -k "redaction or actor or inv6" -x` | ❌ W0 | ⬜ pending |
| 141-02-01 | 02 | 1 | STORE-04 | T-141-03 | Authorized links resolve; unresolved and unauthorized links still produce a row | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py -k "link or unauthorized" -x` | ❌ W0 | ⬜ pending |
| 141-02-02 | 02 | 1 | STORE-03 | T-141-04 | Duplicate user/session/question returns the existing immutable capture | unit | `cd server && uv run pytest tests/initiatives/test_capture_service.py -k idempotent -x` | ❌ W0 | ⬜ pending |
| 141-03-01 | 03 | 2 | OBS-01, OBS-02 | T-141-05 | caller lifecycle is complete and logs contain no body/secrets | unit | `cd server && uv run pytest tests/initiatives/test_capture_observability.py -x` | ❌ W0 | ⬜ pending |
| 141-03-02 | 03 | 2 | STORE-01, MCP-04 | — | Capture remains separate from ProjectMemory, Ledger and report_project_knowledge | regression | `cd server && uv run pytest tests/initiatives/test_capture_service.py::test_persist_does_not_write_memory_or_ledger tests/mcp_tools/test_report_project_knowledge.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/initiatives/test_capture_service.py` — persistence, linking, idempotency and separation tests.
- [ ] `server/tests/initiatives/test_capture_inv6_guard.py` — unique-writer and deferred-sink static guards.
- [ ] `server/tests/initiatives/test_capture_observability.py` — lifecycle, redaction and best-effort logging tests.

---

## Manual-Only Verifications

All Phase 141 behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verification or Wave 0 dependencies.
- [ ] Sampling continuity: no 3 consecutive tasks without automated verification.
- [ ] Wave 0 covers all missing references.
- [ ] No watch-mode flags.
- [ ] Feedback latency < 30s.
- [ ] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending
