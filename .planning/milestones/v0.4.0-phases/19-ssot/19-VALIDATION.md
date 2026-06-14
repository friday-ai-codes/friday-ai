---
phase: 19
slug: ssot
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-13
backfilled: 2026-06-14  # frontmatter 收尾：Wave 0 测试实际全绿（tests/workflows/ 479 passed 复核），回写遗漏标记
---

# Phase 19 — Validation Strategy

> 前后端节点定义单一事实源——前端 vitest + 后端 pytest 双侧验证契约。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (前端)** | `vitest@^4` + `@vue/test-utils` + `happy-dom`（`web/package.json`） |
| **Framework (后端)** | `pytest@>=9` + `pytest-django` + `pytest-asyncio`（`server/pyproject.toml`） |
| **Config file** | `web/vite.config.ts`(test) / `server/pyproject.toml`([tool.pytest]) |
| **Quick run (前端)** | `pnpm -C web test:unit -- src/components/__tests__/node-sync.test.ts` |
| **Quick run (后端)** | `cd server && uv run pytest tests/workflows/test_api.py -k NodeType -x` |
| **Full suite (前端)** | `pnpm -C web test:unit`（CI: `test:unit:coverage`） |
| **Full suite (后端)** | `cd server && uv run pytest tests/workflows/ -x` |
| **Estimated runtime** | 前端 ~数十秒 / 后端 NodeType 子集 ~10s |

---

## Sampling Rate

- **After every task commit:** 相关侧 quick run（前端 node-sync / 后端 NodeType）。
- **After every plan wave:** 双侧 full suite（`pnpm -C web test:unit` + `cd server && uv run pytest tests/workflows/`）。
- **Before `/gsd-verify-work`:** `pnpm -C web lint && pnpm -C web type-check && pnpm -C web test:unit` 全绿 + 后端 `tests/workflows/` 全绿。
- **Max feedback latency:** 60 seconds（quick run）。

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | SSOT-01 | `/api/node-types/` 暴露 ui_schema + default_config；fetch_space_info 在、fetch_project_info 不在；default_config 键 ⊆ config_schema | unit (pytest) | `uv run pytest tests/workflows/test_api.py -k NodeType -x` | ⚠️ 扩展 TestNodeTypeAPI | ⬜ pending |
| TBD | TBD | 0 | SSOT-01 | 前端 palette/默认 config/displayName 经 store 取得（无 NODE_REGISTRY） | unit (vitest) | `pnpm -C web test:unit -- src/composables/__tests__/useNodeMeta*.test.ts` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | SSOT-02 | BaseWorkflowNode 由 store inputs/outputs 渲染 Handle；空 store 回退单 in/out；审批节点出 approved/rejected | component (vitest) | `pnpm -C web test:unit -- src/components/**/BaseWorkflowNode*.test.ts` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | SSOT-03 | 前端残留硬编码节点 ⊆ 后端 fixture；palette types ⊆ fixture；无幽灵节点 | unit (vitest) | `pnpm -C web test:unit -- src/components/__tests__/node-sync.test.ts` | ⚠️ 重写现有 | ⬜ pending |
| TBD | TBD | 0 | SSOT-03 | validate-node-definitions.ts URL = /api/node-types/（不含 workflows/node-types） | unit (vitest) | `pnpm -C web test:unit -- src/components/__tests__/validate-nodes.test.ts` | ⚠️ 加严现有 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] fixture 生成脚本 `web/scripts/generate-node-fixture.ts`（或 Django 管理命令）：从 `NodeRegistry.get_all_schemas()` dump `{node_type, category, inputs[].name, outputs[].name}` 精简集到 `web/src/types/workflow/__fixtures__/node-types.fixture.json` 并入库；提供 `pnpm gen:node-fixture`。
- [ ] 重写 `web/src/components/__tests__/node-sync.test.ts`：删 `EXPECTED_NODES`，改读 fixture 对账（palette types ⊆ fixture、无 fetch_project_info/code_implement/technical_plan 幽灵、parallel/join 端口多 in/out）。
- [ ] 新建 store 适配器单测（`getNodeDefinition/getDefaultConfig/getNodesByCategory` 从 mock store 取值）。
- [ ] 新建 `BaseWorkflowNode` Handle 渲染测试（空 store 回退 + 就绪后真实端口）。
- [ ] 后端 `TestNodeTypeAPI` 扩字段级断言（ui_schema/default_config/fetch_space_info）。
- [ ] 修正 `validate-node-definitions.ts` L77 URL。
- 框架安装：无需（前端 vitest + 后端 pytest 既有）。

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 画布编辑全流程不回退（拖放新节点、连线、配置面板、保存）经真实浏览器观感一致 | SSOT-01/02 | 端到端交互观感需人工 | 打开工作流编辑器，拖入 fetch_space_info / ai_coding / 审批节点，确认 palette 无 fetch_project_info、Handle 正确（plan/coding_result/approved/rejected）、保存往返正常 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
