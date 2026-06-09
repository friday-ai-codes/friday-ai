---
phase: 6
slug: pat
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend, server/), vitest (frontend, web/) |
| **Config file** | `server/pyproject.toml` (pytest/django), `web/vitest.config.ts` |
| **Quick run command** | `cd server && uv run pytest tests/test_access_tokens.py -q` |
| **Full suite command** | `cd server && uv run pytest -q && cd ../web && pnpm test` |
| **Estimated runtime** | ~30–60 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the touched layer
- **After every plan wave:** Run the full suite command
- **Before verification:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-xx | — | 1 | PAT-01/03 | — | note + token_suffix 持久化且不泄漏明文 | unit | `uv run pytest tests/test_access_tokens.py -q` | ❌ W0 | ⬜ pending |
| 06-xx | — | 1 | PAT-02 | — | DB/序列化器/前端均无明文 | unit | `uv run pytest tests/test_no_plaintext_token_in_db.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_access_tokens.py` — 扩展：token_suffix 正向断言（= 明文后4位）、note 持久化与序列化
- [ ] `web/src/components/accessTokens/__tests__/` — ListTable 指纹/备注 spec、Form never 警告 spec
- [ ] `cd server && uv run python manage.py makemigrations --check --dry-run access_tokens` — 迁移冒烟

*Existing pytest + vitest infrastructure covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 创建响应明文一键复制体验 | PAT-02 | 剪贴板交互在 jsdom 下不稳定 | 浏览器创建令牌→点复制→粘贴校验 |
| 永不过期非阻塞提示可见性 | PAT-05 | 视觉呈现 | 选「永不过期」确认 amber 提示出现且不阻断提交 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
