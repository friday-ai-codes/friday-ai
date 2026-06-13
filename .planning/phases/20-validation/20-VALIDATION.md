---
phase: 20
slug: validation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 20 — Validation Strategy

> 保存即合法与模板修复——后端 pytest 为主 + 前端 vitest 验证契约。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | 后端 `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django`；前端 `vitest@^4` + `@vue/test-utils` |
| **Config file** | `server/pyproject.toml`（pytest）；`web/vite.config.ts`(test) |
| **Quick run command** | `cd server && uv run pytest tests/workflows/test_graph_validator.py -x -q` |
| **Full suite command** | `cd server && uv run pytest tests/workflows -q`（须零回归）；`pnpm -C web test:unit` |
| **Estimated runtime** | validator 单测 <10s / 后端 workflows 全量 ~1min |

---

## Sampling Rate

- **After every task commit:** `cd server && uv run pytest tests/workflows/test_graph_validator.py -x -q`（改前端时附 `pnpm -C web test:unit --run <file>`）。
- **After every plan wave:** `cd server && uv run pytest tests/workflows -q`（全量零回归）。
- **Before `/gsd-verify-work`:** 后端 workflows 全绿 + `pnpm -C web test:unit` 全绿 + `pnpm -C web type-check`。
- **Max feedback latency:** 60 seconds（validator 单测）。

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | VAL-01 | 环/入口/孤立/handle/config/变量 命中与放行（default 恒合法、无 schema 跳字段、condition 动态输出） | unit (零 DB) | `uv run pytest tests/workflows/test_graph_validator.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | VAL-02 | bulk-update 非法 config/坏 handle → 400 结构化 errors；合法保存不误拒 | integration (django_db) | `uv run pytest tests/workflows/test_api.py -k bulk -x` | ⚠️ 扩展 | ⬜ pending |
| TBD | TBD | 1 | VAL-02 | 单节点 create 补 config 校验 | integration | `uv run pytest tests/workflows/test_api.py -k node -x` | ⚠️ 扩展 | ⬜ pending |
| TBD | TBD | 1 | VAL-03 | useWorkflowValidationStore 扩类型；IssuesPanel 渲染 errors+warnings；saveWorkflow 接 dry-run/解析 400 | unit (vitest) | `pnpm -C web test:unit` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | TPL-01 | daily_summary 变量解析到真实字段；code_review_pipeline 终态契约对齐可执行 | unit + 执行级 | `uv run pytest tests/workflows/test_template_loader.py -x` | ⚠️ 扩展 | ⬜ pending |
| TBD | TBD | 0 | TPL-02 | 每模板经 validator 零 error；注入坏 node_type/缺必填/坏变量路径/坏 handle → 失败 | unit/integration | `uv run pytest tests/workflows/test_template_loader.py -k validator -x` | ⚠️ 扩展 | ⬜ pending |
| TBD | TBD | 1 | TPL-03 | acreate_workflow_from_template 对非法模板建库前拒绝 + 结构化错误 | integration (async) | `uv run pytest tests/workflows/test_template_loader.py -k from_template -x` | ⚠️ 扩展 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/tests/workflows/test_graph_validator.py` —— VAL-01 全规则（含 Pitfall 1/2 "不误伤"用例：default 边恒合法、无 schema 输出跳字段、condition 动态输出 handle）。
- [ ] 扩展 `server/tests/workflows/test_template_loader.py` —— TPL-01/02/03（每模板零 error + schema 可判定的断裂注入 + loader 建库前拒绝）。
- [ ] 扩展 `server/tests/workflows/test_api.py` —— VAL-02 bulk-update / 单节点 create 400 结构化路径 + 合法不误拒。
- [ ] 前端 `web/src/stores/__tests__/useWorkflowValidationStore.test.ts` + IssuesPanel 渲染测试（VAL-03）。
- 框架安装：无需（pytest/vitest 既有）。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 编辑器保存非法工作流时 IssuesPanel 真实弹出 errors/warnings、保存被拒；修正后可保存 | VAL-03 | 浏览器交互观感 | 编辑器造环/坏 handle，保存，确认 IssuesPanel 展示结构化问题且保存被拒；修正后保存成功 |
| 从 code_review_pipeline / daily_summary 模板创建后给定合法 trigger 执行到业务预期 | TPL-01 | 需真实 webhook payload + 外部依赖 | 用文档化的 webhook payload 触发，确认执行无变量字段错误、跑到通知/审查产出 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
