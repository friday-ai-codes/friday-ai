---
phase: 1
slug: setup-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 1 — Validation Strategy

> 首启向导门禁与初始化状态检测的逐阶段验证契约。后端 pytest + 前端 vitest 双栈。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest 9.x + pytest-asyncio + pytest-django（`server/`） |
| **Framework (frontend)** | vitest 4 + @vue/test-utils + happy-dom（`web/`） |
| **Config file** | `server/pyproject.toml`（pytest/ruff/mypy）；`web/vite.config.ts` + `web/src/test/setup.ts` |
| **Quick run command** | 后端 `cd server && uv run pytest tests/test_setup_gate.py -q`；前端 `cd web && pnpm vitest run src/**/setup*` |
| **Full suite command** | 后端 `cd server && uv run pytest -q`；前端 `cd web && pnpm vitest run` |
| **Estimated runtime** | quick ~10–30s；full 数分钟 |

---

## Sampling Rate

- **After every task commit:** 运行对应的 quick run command（命中本任务新增/改动的测试）
- **After every plan wave:** 运行受影响栈的 full suite（后端或前端）
- **Before `/gsd-verify-work`:** 后端 + 前端 full suite 必须全绿
- **Max feedback latency:** ~60 秒（quick 命令）

---

## Per-Task Verification Map

> 由 planner 在各 PLAN.md 任务的 `<acceptance_criteria>` / `<automated>` 中细化填充。下表为 Phase 1 必须覆盖的核心验证维度（SETUP-01..04）。

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | SETUP-02 | — | `GET /api/auth/setup/status/` 无认证返回 `{needs_setup,is_initialized}` 布尔 | unit/integration | `uv run pytest tests/test_setup_gate.py -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | SETUP-03 | T-1-01 | 存在 superuser 时 `POST /api/auth/setup/` 返回 403（fail-closed） | integration | `uv run pytest tests/test_setup_gate.py -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | SETUP-04 | T-1-02 | 已初始化下并发/重复 POST 一律 403，无法重置/接管 | integration | `uv run pytest tests/test_setup_gate.py -q` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | SETUP-01 | — | 无 superuser 时任意路由经守卫重定向到 `/setup`；已初始化访问 `/setup` 重定向离开 | unit | `pnpm vitest run` | ❌ W0 | ⬜ pending |
| TBD | 02 | 2 | SETUP-02 | — | 守卫据 `getSetupStatus()` 放行/拦截；fetch 失败按已初始化处理 | unit | `pnpm vitest run` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/test_setup_gate.py` — SETUP-02/03/04 的后端测试桩（含 superuser fixture、async client、并发/重复拒绝断言）
- [ ] `web/src/**/__tests__/setup*.spec.ts` — 路由守卫与 `api/setup.ts` 的前端测试桩
- [ ] 既有 `server/tests/conftest.py` / `web/src/test/setup.ts` 提供共享 fixture，无需新增框架

*既有 pytest + vitest 基础设施已覆盖全部需求所需框架；Wave 0 仅新增测试文件骨架。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 全新部署端到端首访自动进向导 | SETUP-01 | 端到端浏览器跳转最直观由人工确认（自动化覆盖守卫单元逻辑） | 全新 DB（无 superuser）启动 server+web，浏览器访问 `/` → 应跳到 `/setup` |

*其余 SETUP-02/03/04 行为均有自动化覆盖。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
