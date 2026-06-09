---
phase: 8
slug: iso
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 8 — Validation Strategy

> Per-phase validation contract. An isolation phase is all-or-nothing: EVERY access path needs an explicit cross-user-denied test.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django, pytest-asyncio), DRF APIClient |
| **Config file** | `server/pyproject.toml` |
| **Quick run command** | `cd server && uv run pytest tests/test_conversation_isolation.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/test_chat_views.py tests/test_conversation_integration.py tests/test_conversation_isolation.py tests/test_coding_session_service.py -q` |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** quick run command
- **After every plan wave:** full suite command
- **Before verification:** full suite green; every enumerated conversation path has a cross-user-denied (404) test
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 08-xx | — | 1 | ISO-01 | Conversation.created_by set on create; history → earliest superuser | unit/migration | `uv run pytest tests/test_conversation_isolation.py -q` | ❌ W0 | ⬜ pending |
| 08-xx | — | 1 | ISO-02 | 普通用户全路径仅见/操作自己会话 | integration | `uv run pytest tests/test_conversation_isolation.py -q` | ❌ W0 | ⬜ pending |
| 08-xx | — | 1 | ISO-03 | 管理员 AI 对话默认仅见自己（无 superuser bypass） | integration | `uv run pytest tests/test_conversation_isolation.py -q` | ❌ W0 | ⬜ pending |
| 08-xx | — | 1 | ISO-04 | 越权访问他人会话（含 SSE/对象级操作/coding-session）→ 404，不泄漏存在性 | integration | `uv run pytest tests/test_conversation_isolation.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_conversation_isolation.py`（新）— 覆盖 RESEARCH 列出的 **全部 25 个** 会话访问路径的 cross-user-denied（404）；新建会话 created_by；管理员无 bypass
- [ ] 既有 fixture 更新：创建 Conversation 时补 `created_by`（避免回归套件大面积 break）
- [ ] 迁移冒烟：`makemigrations --check`；RunPython 回填可逆

*Existing pytest infra covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Web UI 中用户只看到自己的会话列表、打不开他人会话 | ISO-02/03 | 浏览器多账号体验 | 两个账号各建会话，互相访问对方会话 URL → 404 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] EVERY conversation access path has a cross-user-denied test (all-or-nothing)
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
