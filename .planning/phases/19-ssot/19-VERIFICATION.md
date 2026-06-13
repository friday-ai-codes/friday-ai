---
phase: 19-ssot
verified: 2026-06-13T18:44:00Z
status: passed
status_note: "3/3 自动化 must-haves 全过；唯一人工浏览器观感项按自主模式 deferred 至里程碑收尾（沿用 v0.1.0-v0.3.0 human_needed deferral 惯例），不阻塞阶段推进"
score: 3/3 must-haves verified
overrides_applied: 0
human_verification:
  - test: "在工作流编辑器拖入 fetch_space_info / ai_coding / 审批节点，连线、打开配置面板、保存往返"
    expected: "palette 无 fetch_project_info、出现 fetch_space_info；ai_coding 显示 plan 输入、ai_code_review 显示 coding_result 输入、审批节点显示 approved/rejected 输出；删除 NODE_REGISTRY 后拖放/默认 config/显示名/连线校验/保存均不回退；打开存量老工作流连线不退化为 default"
    why_human: "真实浏览器端到端交互观感（拖放、Handle 视觉位置、保存往返、存量 edge 不退化）无法通过 grep/静态分析验证；为 19-VALIDATION.md 明确登记的 Manual-Only 项"
---

# Phase 19: 节点定义单一事实源 Verification Report

**Phase Goal:** 后端节点 registry 成为唯一事实源——前端面板、表单、画布端口全部由 `GET /api/node-types/` 驱动，前后端节点定义不再漂移
**Verified:** 2026-06-13T18:44:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth (ROADMAP Success Criteria) | Status | Evidence |
| --- | -------------------------------- | ------ | -------- |
| 1   | 前端 palette/表单 schema/默认 config 全部由 `GET /api/node-types/` 驱动，`NODE_REGISTRY` 删除后画布功能不回退，幽灵节点 `fetch_project_info` 不再出现（指向 `fetch_space_info`） | ✓ VERIFIED | `rg NODE_REGISTRY web/src` 零命中；`registry.ts` helper(`getNodeDefinition/getDefaultConfig/getNodesByCategory/validateNodeConfig`) 经 `useNodeTypesStore` 适配（L83-196）；`default_config` 取后端字段；`rg fetch_project_info web` 全仓零命中；`pnpm type-check` exit 0；全量 vitest 998 passed |
| 2   | 画布 Handle 按后端 NodePort 渲染：`ai_coding` 显示 `plan`、`ai_code_review` 显示 `coding_result`、审批节点显示 `approved`/`rejected`，`portConfig.ts` 硬编码被替换 | ✓ VERIFIED | `BaseWorkflowNode.vue` `ports` computed 读 `store.getNodeType().inputs/outputs`（L55-67）+ 空 store 最小回退；fixture 确认 ai_coding inputs=[plan]、ai_code_review inputs=[coding_result,plan]、ai_plan_approval outputs=[approved,rejected]；`BaseWorkflowNode.test.ts` 通过 |
| 3   | 前后端一致性 CI 守护：节点 type/端口漂移时 CI 失败 | ✓ VERIFIED | `node-sync.test.ts` 改 fixture 驱动（import `node-types.fixture.json`，删 `EXPECTED_NODES`）；`validate-node-definitions.ts` URL 修正为 `/api/node-types/`；`validate-nodes.test.ts` 断言 `not.toContain('workflows/node-types')`；后端 `TestNodeTypeAPI` 字段级 + 幽灵缺席断言（3 passed） |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/workflows/nodes/base.py` | `_get_default_config` + `get_schema` 增 default_config | ✓ VERIFIED | L592-603 定义、L616 调用；空 schema 安全返回 `{}` |
| `server/workflows/api/serializers.py` | NodeTypeSerializer 暴露 ui_schema + default_config | ✓ VERIFIED | L805-806 两字段，execution_mode 亦在 |
| `server/workflows/migrations/0026_*.py` | 幂等 fetch_project_info→fetch_space_info 迁移 | ✓ VERIFIED | filter().update() + RunPython.noop；依赖 0025；`showmigrations` 显示 [X] 已应用；`makemigrations --check` 无漂移 |
| `server/workflows/management/commands/dump_node_fixture.py` | 从 NodeRegistry dump 精简 fixture | ✓ VERIFIED | 文件存在；fixture 33 节点确定性排序 |
| `web/src/types/workflow/__fixtures__/node-types.fixture.json` | 离线节点快照 | ✓ VERIFIED | node_count=33，含 fetch_space_info、无 fetch_project_info |
| `web/src/types/workflow/registry.ts` | store 适配器 helper + CONFIG_COMPONENTS，删 NODE_REGISTRY | ✓ VERIFIED | CONFIG_COMPONENTS 16 项保留；validateNodeConfig 降级轻量校验；configComponent 经 CONFIG_COMPONENTS 注入 |
| `web/src/stores/useNodeTypesStore.ts` | NodeType 扩 ui_schema/default_config/execution_mode | ✓ VERIFIED | type-check 通过、registry 适配器消费三字段 |
| `web/src/components/.../BaseWorkflowNode.vue` | Handle 由 store inputs/outputs 渲染 | ✓ VERIFIED | L41/L55-67 |
| `web/src/components/.../portConfig.ts` | migratePortId 保留（D-02） | ✓ VERIFIED | `export function migratePortId` L106；被 useWorkflowsStore.toStoreEdges 调用 |
| `web/.../editor/nodes/nodeVisuals.ts` | 前端视觉源保留、幽灵改名 | ✓ VERIFIED | L50 `fetch_space_info`，无幽灵 |
| `IntegrationNode.vue` | 死代码核实/删除 | ✓ VERIFIED | 已删除；除 components.d.ts 外无引用 |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| BaseNode.get_schema() | NodeTypeSerializer | default_config/ui_schema key 暴露 | ✓ WIRED |
| registry.ts helpers | useNodeTypesStore | toDefinition 适配 snake→camel | ✓ WIRED |
| BaseWorkflowNode ports | store.getNodeType().inputs/outputs | computed 响应式 + 最小回退 | ✓ WIRED |
| node-sync.test.ts | node-types.fixture.json | import fixture 对账 | ✓ WIRED |
| 0026 migration | WorkflowNode.node_type | filter().update() | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| BaseWorkflowNode.vue | ports | `useNodeTypesStore.getNodeType().inputs/outputs`（后端 /api/node-types/） | 是（fixture 证实真实端口集） | ✓ FLOWING |
| registry.ts helpers | NodeTypeDefinition | store nodeTypes（后端 API） | 是 | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端 /api/node-types/ 暴露字段 + 幽灵缺席 | `pytest test_api.py -k NodeType` | 3 passed | ✓ PASS |
| fixture 端口语义 | `node -e` 校验 ai_coding/ai_code_review/ai_plan_approval 端口 | plan / coding_result+plan / approved+rejected | ✓ PASS |
| 前端类型完整性 | `pnpm -C web type-check` | exit 0 | ✓ PASS |
| 前端全量单测 | `pnpm -C web test:unit --run` | 998 passed / 1 skipped / 0 failed | ✓ PASS |
| 迁移幂等/无漂移 | `makemigrations --check` | No changes detected | ✓ PASS |

### Probe Execution

无项目级 `scripts/*/tests/probe-*.sh` 探针，且本阶段 PLAN/SUMMARY 未声明探针——SKIPPED（验证以 pytest/vitest/type-check 自动化命令替代）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SSOT-01 | 19-01/02/03 | palette/schema/默认 config 由 API 驱动，删 NODE_REGISTRY，幽灵→fetch_space_info | ✓ SATISFIED | Truth 1 + 迁移 0026 + registry store 适配 |
| SSOT-02 | 19-04 | Handle 按后端 NodePort 渲染，替换 portConfig | ✓ SATISFIED | Truth 2 + BaseWorkflowNode.test.ts |
| SSOT-03 | 19-01/05 | 前后端一致性自动化守护 | ✓ SATISFIED | Truth 3 + fixture 驱动 node-sync + 后端字段断言 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 修改源文件中无 TBD/FIXME/XXX 债务标记 | — | 无 |

注：19-05 deferred-items.md 记录的 `pnpm lint` pre-existing 失败（`web/.pytest_cache/README.md`、`AISummarySection.vue`）均为非本阶段文件，属 SCOPE BOUNDARY，不计入本阶段缺陷。

### Implementation Decisions（D-01..D-05）核验

| 决策 | 要求 | 核验结果 |
| ---- | ---- | -------- |
| D-01 | serializer 补 ui_schema/default_config；保留 node-definitions.json 注入链路 | ✓ 两字段已暴露；`node-definitions/` 目录与构建期注入（node_definitions_json_loaded）保留 |
| D-02 | 删 NODE_REGISTRY legacy；migratePortId 保留 | ✓ NODE_REGISTRY 零命中；migratePortId 保留并被调用 |
| D-03 | fetch_project_info 全量 → fetch_space_info + 数据迁移 | ✓ 全仓零命中 fetch_project_info；迁移 0026 已应用 |
| D-04 | Handle 由 API inputs/outputs 渲染 + 最小回退 | ✓ BaseWorkflowNode ports computed + default 回退 |
| D-05 | validate-node-definitions URL 修正；node-sync fixture 驱动 | ✓ URL=/api/node-types/；node-sync import fixture |

### Human Verification Required

#### 1. 画布编辑全流程端到端观感

**Test:** 打开工作流编辑器，从 palette 拖入 `fetch_space_info`、`ai_coding`、审批节点；连线、打开配置面板、保存并重新加载；另打开一个含存量节点的老工作流。
**Expected:** palette 无 `fetch_project_info`、出现 `fetch_space_info`；`ai_coding` 显示 `plan` 输入、`ai_code_review` 显示 `coding_result` 输入、审批节点显示 `approved`/`rejected` 输出；拖放/默认 config/显示名/连线校验/保存往返均正常（不回退）；老工作流连线不退化为 default 句柄。
**Why human:** 真实浏览器交互观感、Handle 视觉位置、保存往返与存量 edge 兼容性无法通过 grep/静态分析或单测完全覆盖（19-VALIDATION.md 明确登记的 Manual-Only 项）。

### Gaps Summary

无阻塞性缺口。3/3 ROADMAP Success Criteria 在代码 + 自动化测试层面均已验证：后端 `NodeTypeSerializer` 暴露 `ui_schema`/`default_config`，前端 `NODE_REGISTRY` legacy 已删除、helper 全部经 `useNodeTypesStore` 驱动，画布 Handle 由后端 NodePort 渲染，幽灵节点 `fetch_project_info` 全仓清零并有幂等数据迁移兜底，一致性守护改为离线 fixture 驱动。`migratePortId`、`nodeVisuals`、`CONFIG_COMPONENTS`（configComponent）均按 D-02 保留未误删。

状态判定为 `human_needed` 的唯一原因：19-VALIDATION.md 登记了一项 Manual-Only 端到端浏览器观感验证（拖放/连线/保存/存量 edge 不退化），按验证决策树该人工项优先于全自动通过。所有可自动化的断言均已通过（pytest 3 passed、type-check exit 0、vitest 998 passed、迁移无漂移）。

---

_Verified: 2026-06-13T18:44:00Z_
_Verifier: Claude (gsd-verifier)_
