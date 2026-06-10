---
phase: 9
slug: admvw
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for the admin read-only session console.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django, pytest-asyncio), DRF APIClient; vitest (frontend) |
| **Config file** | `server/pyproject.toml`, `web/vitest.config.ts` |
| **Quick run command** | `cd server && uv run pytest tests/test_admin_conversations.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/test_admin_conversations.py tests/test_conversation_isolation.py -q && cd ../web && pnpm vitest run src/pages/admin` |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** quick run command
- **After every plan wave:** full suite command
- **Before verification:** full suite green; Phase 8 isolation suite still 100% green (admin endpoints must NOT weaken it)
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 09-xx | — | 1 | ADMVW-01 | superuser 可列出/查看所有用户会话；非 superuser → 403 | integration | `uv run pytest tests/test_admin_conversations.py -q` | ❌ W0 | ⬜ pending |
| 09-xx | — | 1 | ADMVW-02 | admin 端点只读：写方法 405；他人会话不可续聊 | integration | `uv run pytest tests/test_admin_conversations.py -q` | ❌ W0 | ⬜ pending |
| 09-xx | — | 1 | ADMVW-03 | admin fork → created_by=admin、复制消息、status=DRAFT；之后可经普通路径续聊 | integration | `uv run pytest tests/test_admin_conversations.py -q` | ❌ W0 | ⬜ pending |
| 09-xx | — | 1 | (regression) | Phase 8 普通路径隔离仍全绿（admin 端点不削弱） | integration | `uv run pytest tests/test_conversation_isolation.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_admin_conversations.py`（新）— 非 admin 403、admin 看全部、只读 405、fork 归属 admin + status=DRAFT + 消息复制
- [ ] `web/src/pages/admin/__tests__/`（新）— admin 会话页渲染/只读/ fork 动作 spec
- [ ] Phase 8 回归基线：`test_conversation_isolation.py` 必须保持全绿

*Existing pytest + vitest infra covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 管理员后台浏览所有会话并只读查看消息 | ADMVW-01/02 | 浏览器多账户 + 表格/查看器 UX | 以管理员登录 → 会话管理页 → 看到他人会话 → 打开只读详情（无输入框） |
| fork 到自己名下后可续聊 | ADMVW-03 | 端到端跳转 + owner 续聊 | fork 他人会话 → 跳转 chat → 以 owner 身份发消息成功 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Admin endpoints do NOT weaken Phase 8 isolation (regression green)
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
