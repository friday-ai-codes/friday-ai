---
phase: 7
slug: ident
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django, pytest-asyncio), DRF APIClient |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/test_auth.py tests/test_access_tokens.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/test_auth.py tests/test_auth_e2e.py tests/test_access_tokens.py tests/test_interactions_ledger.py tests/mcp_tools -q` |
| **Estimated runtime** | ~30–90 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before verification:** Full suite green (incl. mcp_tools + auth e2e — global auth-class change has wide blast radius)
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-xx | — | 1 | IDENT-01 | — | 有效 PAT → request.user == owner | unit | `uv run pytest tests/test_access_tokens.py -q` | ❌ W0 | ⬜ pending |
| 07-xx | — | 1 | IDENT-02 | — | PAT 与 JWT 同用 Bearer 互不吞；顺序正确 | unit | `uv run pytest tests/test_auth.py -q` | ❌ W0 | ⬜ pending |
| 07-xx | — | 1 | IDENT-03 | — | MCP 匿名请求 401/403 fail-closed | integration | `uv run pytest tests/mcp_tools -q` | ❌ W0 | ⬜ pending |
| 07-xx | — | 1 | IDENT-04 | — | InteractionRun fingerprint 仍记录 | unit | `uv run pytest tests/test_interactions_ledger.py -q` | ✅ | ⬜ pending |
| 07-xx | — | 1 | IDENT-05 | — | 吊销/过期 token 一律拒 | unit | `uv run pytest tests/test_access_tokens.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_access_tokens.py` — 更新 `test_valid_token_passes`：`request.user == created_by`（曾断言 `user is None`）
- [ ] `server/tests/test_pat_identity.py`（新）— PAT 身份认证、owner RBAC、PAT/JWT 共存顺序、非 friday_pat_ 让行
- [ ] `server/tests/mcp_tools/` — MCP fail-closed 匿名拒绝 + 错误码 `authentication_failed`
- [ ] 回归：`test_auth.py` / `test_auth_e2e.py` 401 头不被降级为 403（`authenticate_header` 修复）

*Existing pytest infra covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Web UI cookie-JWT 登录全链路不受认证类顺序变更影响 | IDENT-02 | 端到端浏览器登录态 | 浏览器登录 → 访问受保护页面 → 正常 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
