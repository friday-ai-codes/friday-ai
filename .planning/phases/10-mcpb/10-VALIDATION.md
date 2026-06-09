---
phase: 10
slug: mcpb
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for token binding + RemoteTool execution endpoint.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pytest-django, pytest-asyncio), DRF APIClient; vitest (frontend) |
| **Config file** | `server/pyproject.toml`, `web/vitest.config.ts` |
| **Quick run command** | `cd server && uv run pytest tests/test_tool_bindings.py -q` |
| **Full suite command** | `cd server && uv run pytest tests/test_tool_bindings.py tests/test_remote_tool_execute.py -q && cd ../web && pnpm vitest run src/components/toolBindings` |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** quick run command
- **After every plan wave:** full suite command
- **Before verification:** full suite green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 10-xx | — | 1 | MCPB-01 | 用户可把自己的 PAT 绑给 mcp/skill 工具（绑定入库，upsert） | unit/integration | `uv run pytest tests/test_tool_bindings.py -q` | ❌ W0 | ⬜ pending |
| 10-xx | — | 1 | MCPB-01 | 不能引用他人令牌 id 绑定（access_token.created_by == request.user 校验） | integration | `uv run pytest tests/test_tool_bindings.py -q` | ❌ W0 | ⬜ pending |
| 10-xx | — | 1 | MCPB-03 | 用户仅能 list/unbind 自己的绑定；序列化不泄漏明文 | integration | `uv run pytest tests/test_tool_bindings.py -q` | ❌ W0 | ⬜ pending |
| 10-xx | — | 1 | RTOOL-01 | PAT 认证、按 name 执行 RemoteTool；匿名 fail-closed 401/403 | integration | `uv run pytest tests/test_remote_tool_execute.py -q` | ❌ W0 | ⬜ pending |
| 10-xx | — | 1 | MCPB-02 | 执行端点以 owner 身份运行（request.user=owner，审计 fingerprint=token_hash） | integration | `uv run pytest tests/test_remote_tool_execute.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_tool_bindings.py`（新）— 绑定 upsert / owner 隔离 / 跨用户令牌引用拒绝 / unbind / bindable-list 过滤(mcp,skill) / 无明文泄漏
- [ ] `server/tests/test_remote_tool_execute.py`（新）— PAT 认证执行、匿名 401/403、工具不存在错误、审计 run 创建
- [ ] `server/tests/conftest.py` — 补 `make_remote_tool` + `make_tool_binding` fixtures
- [ ] `web/src/components/toolBindings/__tests__/`（新）— 绑定管理 UI spec

*Existing pytest + vitest infra covers the rest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 用户在界面把令牌绑给 skill/mcp 并解绑 | MCPB-01/03 | 浏览器交互 | 设置页选工具 → 选令牌 → 绑定 → 看到绑定 → 解绑 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] No plaintext token in any binding/list response
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
