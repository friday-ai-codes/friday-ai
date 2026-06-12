---
phase: 16
slug: expo
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-12
updated: 2026-06-12
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend framework** | pytest >=9.0.2 + pytest-django + pytest-asyncio |
| **Frontend framework** | vitest ^4 + @vue/test-utils + happy-dom |
| **Config** | `server/pyproject.toml` / `web/vite.config.ts` |
| **Quick backend** | `cd server && uv run pytest tests/knowledge/test_exposure.py tests/mcp_tools/test_delivery_knowledge_tools.py -x` |
| **Quick frontend** | `cd web && pnpm exec vitest run src/components/knowledge src/pages/knowledge --passWithNoTests` |
| **Estimated runtime** | backend quick ~30s / full ~90s · frontend ~20s |

---

## Sampling Rate

- **After every task commit:** plan task `<automated>` command
- **After Wave 1:** MCP + exposure + timeline as_of 套件
- **After Wave 2:** + chat tools + workflow node + skills grep gates
- **After Wave 3:** + knowledge API + entity detail vitest
- **Before `/gsd-verify-work`:** 全量相关 pytest + vitest + `manage.py check`
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01 Task 1 | 16-01 | 1 | EXPO-01, ENH-04 | T-16-03 | as_of 严格解析；timeline bi-temporal | unit | `cd server && uv run pytest tests/knowledge/test_exposure.py tests/knowledge/test_timeline.py -k "as_of or exposure" -x` | ❌ 本任务创建 | ⬜ pending |
| 16-01 Task 2 | 16-01 | 1 | EXPO-01 | T-16-01, T-16-04 | PAT 认证；schema snapshot 22 工具 | api | `cd server && uv run pytest tests/mcp_tools/test_schema_snapshot.py -x` | ✅ 扩展 | ⬜ pending |
| 16-01 Task 3 | 16-01 | 1 | EXPO-01, ENH-04 | T-16-02 | A PAT 查 B 项目空结果 | integration | `cd server && uv run pytest tests/mcp_tools/test_delivery_knowledge_tools.py -x` | ❌ 本任务创建 | ⬜ pending |
| 16-02 Task 1 | 16-02 | 2 | EXPO-03 | — | schema 契约 | unit | `cd server && uv run pytest tests/agents/tools/test_delivery_knowledge_tools.py -k schema -x` | ❌ 本任务创建 | ⬜ pending |
| 16-02 Task 2 | 16-02 | 2 | EXPO-03, ENH-04 | T-16-05, T-16-06 | owner principal；越权空 | unit | `cd server && uv run pytest tests/agents/tools/test_delivery_knowledge_tools.py -x` | ✅ Task 1 创建 | ⬜ pending |
| 16-03 Task 1 | 16-03 | 2 | EXPO-02 | T-16-08 | 失败降级不阻塞 | unit | `cd server && uv run pytest tests/workflows/test_delivery_knowledge_search_node.py -k "node" -x` | ❌ 本任务创建 | ⬜ pending |
| 16-03 Task 2 | 16-03 | 2 | EXPO-02, ENH-04 | T-16-07 | 飞轮 hook；config UI 存在 | unit+fe | `cd server && uv run pytest tests/workflows/test_delivery_knowledge_search_node.py -k plan_generation -x && test -f web/src/components/workflow/config/DeliveryKnowledgeSearchConfig.vue` | ❌ 本任务创建 | ⬜ pending |
| 16-04 Task 1 | 16-04 | 2 | EXPO-04 | — | 三工具名文档 | doc | `rg -c "search_delivery_knowledge" skills/skills/friday-knowledge/SKILL.md` | ❌ 本任务创建 | ⬜ pending |
| 16-04 Task 2 | 16-04 | 2 | EXPO-04 | — | using-friday 路由；6 skills README | doc | `rg "friday-knowledge" skills/skills/using-friday/SKILL.md skills/README.md` | ✅ 扩展 | ⬜ pending |
| 16-05 Task 1 | 16-05 | 3 | ENH-03, ENH-04 | T-16-10 | entity REST；越权 404 | api | `cd server && uv run pytest tests/knowledge/test_knowledge_api.py -x` | ❌ 本任务创建 | ⬜ pending |
| 16-05 Task 2 | 16-05 | 3 | ENH-03 | T-16-11 | 组件渲染；外链 noopener | component | `cd web && pnpm exec vitest run src/components/knowledge --passWithNoTests` | ❌ 本任务创建 | ⬜ pending |
| 16-05 Task 3 | 16-05 | 3 | ENH-03, ENH-04 | — | as-of invalidate；详情页 | component | `cd web && pnpm exec vitest run src/pages/knowledge/__tests__/entity-detail.spec.ts -x` | ❌ 本任务创建 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> 测试随实现 task 同 plan 交付。无独立 Wave 0 scaffold plan。

- [ ] `test_exposure.py` — 16-01 Task 1
- [ ] `test_timeline.py` as_of 扩展 — 16-01 Task 1
- [ ] `test_delivery_knowledge_tools.py` — 16-01 Task 3
- [ ] `test_delivery_knowledge_tools.py` (agents) — 16-02
- [ ] `test_delivery_knowledge_search_node.py` — 16-03
- [ ] `test_knowledge_api.py` — 16-05 Task 1
- [ ] `entity-detail.spec.ts` — 16-05 Task 3

---

## Manual-Only Verifications

| ID | Scenario | When |
|----|----------|------|
| M-16-01 | 浏览器打开 `/knowledge/entities/:id`，切换 as-of 见版本差异 | Wave 3 完成后 UAT |
| M-16-02 | 外部 MCP client（Codex）调三工具 + PAT | Wave 2 完成后 |
| M-16-03 | 工作流拖入 delivery_knowledge_search 配置 top_k/as_of 并执行 | Wave 2 完成后 |

---

## Nyquist Compliance Checklist

- [x] Every task has `<automated>` in PLAN.md
- [x] VALIDATION.md maps task → command
- [x] Cross-user fail-closed covered (16-01 Task 3, 16-02 Task 2, 16-05 Task 1)
- [x] ENH-04 as_of covered MCP/chat/workflow/REST/frontend
