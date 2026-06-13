---
phase: 19-ssot
plan: 04
subsystem: ui
tags: [vue3, pinia, typescript, vue-flow, handle-rendering, port-config, vue-tsc, vitest]

# Dependency graph
requires:
  - phase: 19-01
    provides: GET /api/node-types/ 暴露 inputs/outputs（NodePort 事实源）
  - phase: 19-03
    provides: useNodeTypesStore 为唯一运行时源；registry helper 改 store 适配器、删 NODE_REGISTRY
provides:
  - BaseWorkflowNode.vue Handle 由 useNodeTypesStore.inputs/outputs 渲染 + 最小回退（D-04）
  - portConfig.getDefaultPortsForNodeType 退出正常渲染路径，仅作 migratePortId 静态回退源；migratePortId 保留（D-02）
  - pages/workflows/[id].vue fetchNodeTypes 顺序化先于 fetchWorkflow（Pitfall 4）+ hasTriggers 由 category 派生
affects: [19-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "画布 Handle 以后端 NodePort 为准：ports computed 读 store inputs/outputs，store ref 就绪后自动重渲染"
    - "store 未就绪最小回退（单 in/单 out default），防首帧空 Handle（Pitfall 1）"
    - "硬编码节点类型集合（触发器）由后端 category 派生，去除前端类型列表漂移"
    - "顺序化取数：先 fetchNodeTypes 后 fetchWorkflow，保证 migratePortId/Handle 端口就绪"

key-files:
  created:
    - web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts
  modified:
    - web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue
    - web/src/pages/workflows/[id].vue
    - web/src/components/workflow/editor/utils/portConfig.ts
    - web/src/stores/useWorkflowsStore.ts

key-decisions:
  - "测试经真实 pinia 注入 store.nodeTypes（不新增 store API；未触碰 useNodeTypesStore.ts，符合 files_modified 边界）"
  - "portConfig.getDefaultPortsForNodeType 不删除：仍被 migratePortId 与 node-sync.test.ts(parallel/join) 消费，仅文档化为回退源"
  - "Handle/NodeToolbar/vue-router/useToast 在组件测试中以轻量 stub 替身，聚焦端口渲染断言"

patterns-established:
  - "RESEARCH Pattern 3：BaseWorkflowNode ports computed 从 store inputs/outputs 渲染 + 最小回退"
  - "RESEARCH Pattern 4：派生节点类型集合（category）替换硬编码 NODE_TYPES 列表"
  - "RESEARCH Pitfall 4：[id].vue 顺序化 await，migratePortId 用静态回退表保证存量 edge 不退化"

requirements-completed: [SSOT-02]

# Metrics
duration: ~18min
completed: 2026-06-13
---

# Phase 19 Plan 04: 画布 Handle 由后端 NodePort 渲染 + 最小回退 + portConfig 降级 Summary

**把 `BaseWorkflowNode.vue` 的 Handle 改由 `useNodeTypesStore` 的 `inputs/outputs`（后端 NodePort）响应式渲染、store 未就绪时回退最小端口；`portConfig.ts` 的 `getDefaultPortsForNodeType` 退出正常渲染路径并保留 `migratePortId` 作存量 edge 兼容；`[id].vue` 取数顺序化（fetchNodeTypes 先行）并由后端 `category` 派生 `hasTriggers`。**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-13
- **Tasks:** 2
- **Files modified:** 5（1 新建 + 4 修改）

## Accomplishments
- `BaseWorkflowNode.vue` `ports` computed 改读 `nodeTypesStore.getNodeType(nodeType).inputs/outputs`，以后端 NodePort 为准（D-04）；`inputPorts`/`outputPorts`/`portLeft` 与模板 Handle `v-for` 全部保留
- store 未就绪（首帧/离线，`getNodeType` 返回 undefined）→ 回退最小端口 `[{id:'default',group:'input'},{id:'default',group:'output'}]`，防首帧空 Handle（Pitfall 1）；computed 依赖 store ref，`fetchNodeTypes` 就绪后自动重渲染
- 新建 `BaseWorkflowNode.test.ts`（@vue/test-utils + happy-dom，4 用例）：空 store 回退、`ai_coding` 渲染 `plan` 输入、`ai_code_review` 渲染 `coding_result` 输入、审批节点 outputs 含 `approved`/`rejected`
- `[id].vue`：`onMounted` 改为 `await fetchNodeTypes()` 先于 `await fetchWorkflow(id)`（顺序化，Pitfall 4）；`hasTriggers` 改由 `store.getNodeType(type)?.category === 'trigger'` 派生，移除 `TRIGGER_NODE_TYPES` import/使用
- `portConfig.ts`：文档化 `getDefaultPortsForNodeType` 退出正常渲染路径、仅作 `migratePortId` 静态端口顺序回退源；`migratePortId` 按 D-02 保留（正则 `^(input|output)-\d+$` 守卫，新句柄透传）
- `useWorkflowsStore.toStoreEdges`：保持调用 `migratePortId`，补注释说明其用静态回退表 + `[id].vue` 顺序化双重保证存量 edge 不退化为 default

## Task Commits

1. **Task 1: BaseWorkflowNode Handle 由 store 端口渲染 + 最小回退 + 组件测试** - `25381e4d4` (feat)
2. **Task 2: [id].vue 顺序化取数 + category 派生触发器 + portConfig 降级** - `da0c06c39` (feat)

## Files Created/Modified
- `web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue` - 引入 `useNodeTypesStore`，`ports` computed 改读 store inputs/outputs + 最小回退；移除 `getDefaultPortsForNodeType` import
- `web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts`（新建）- Handle 渲染组件测试（4 用例，stub Handle/NodeToolbar/router/toast）
- `web/src/pages/workflows/[id].vue` - 顺序化 `fetchNodeTypes`→`fetchWorkflow`；`hasTriggers` category 派生；移除 `TRIGGER_NODE_TYPES` 依赖
- `web/src/components/workflow/editor/utils/portConfig.ts` - 文档化 `getDefaultPortsForNodeType` 降级为 `migratePortId` 回退源；`migratePortId` 保留
- `web/src/stores/useWorkflowsStore.ts` - `toStoreEdges` 注释顺序化/静态回退表保证存量 edge 不退化

## Decisions Made
- **测试经真实 pinia 注入 `store.nodeTypes`，不新增 store API**：plan 行文用 `setNodeTypes` 仅为"注入节点类型"的简称；`useNodeTypesStore` 未导出该 action，且 `files_modified` 不含 `useNodeTypesStore.ts`。测试用 `setActivePinia(createPinia())` + 直接赋值 `store.nodeTypes = [...]`，断言 computed 自动重渲染，语义等价且不越界。
- **`getDefaultPortsForNodeType` 不删除、仅降级**：仍被 `migratePortId`（端口顺序回退）与 `node-sync.test.ts`（parallel 多输出 / join 多输入断言）消费，删除会破坏存量 edge 迁移与既有测试；改为文档化"退出正常渲染路径"。
- **组件测试 stub 外部框架依赖**：`@vue-flow/core`（Handle/Position/useVueFlow）、`@vue-flow/node-toolbar`、`vue-router`、`useToast` 以轻量 stub 替身，Handle stub 暴露 `data-handle-id`/`data-handle-type` 供端口断言，聚焦渲染契约不引入画布全栈。

## Deviations from Plan

None - 计划按原样执行，无 Rule 1-4 偏离。仅一处 grep 门禁适配（非偏离）：`[id].vue` 注释最初含字面量 `TRIGGER_NODE_TYPES`，会触发 acceptance 门禁 `rg "TRIGGER_NODE_TYPES"` 命中；改写为"硬编码触发器类型列表"以满足"无命中"。

## Verification Evidence
- `pnpm -C web exec vitest run src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts` → **4 passed**（空 store 回退 + ai_coding(plan) + ai_code_review(coding_result) + 审批节点(approved/rejected)）
- `pnpm -C web type-check`（vue-tsc --noEmit）→ **exit 0**
- `pnpm -C web exec vitest run src/components/workflow/editor` → **3 files / 31 passed**
- `pnpm -C web exec vitest run src/components/__tests__/node-sync.test.ts` → **5 passed**（parallel/join 端口断言仍绿，确认 portConfig 兼容）
- grep 门禁：`rg "export function migratePortId" portConfig.ts` 命中；`rg "TRIGGER_NODE_TYPES" [id].vue` 无命中；`fetchNodeTypes` 先于 `fetchWorkflow` await

## Issues Encountered
- 无新增依赖、无 uv.lock/pnpm-lock 变更。

## Deferred Issues
- **`web/src/components/__tests__/workflow-data-table.test.ts` 2 用例失败（pre-existing，非本计划文件）**：`getActivePinia() was called but there was no active Pinia` —— 源于 19-03 把 `registry.getNodeDefinition` 改为运行时读 `useNodeTypesStore`，而该测试未补 `setActivePinia`。与 19-04 改动文件无关（未触碰 `WorkflowDataTable.vue`/其测试），按 SCOPE BOUNDARY 记录不修，详见 `deferred-items.md`。建议归 19-05（D-05 测试体系）补 pinia setup。
- 附加上下文提及的 codegraph/conversations 3 个无关超时慢测试，本计划相关测试均绿，未受影响。

## TDD Gate Compliance
Task 1 标注 `tdd="true"`，但 `config.json` `tdd_mode: false` 且 orchestrator 未传 MVP_MODE/TDD_MODE，未强制 RED→GREEN 分提交序列门禁。实务上 Task 1 同时落地实现 + `BaseWorkflowNode.test.ts`（4 passed），覆盖等价（空 store 回退 + 就绪后真实端口）。

## Next Phase Readiness
- 画布输入/输出 Handle 已以后端 NodePort 为准（plan/coding_result/approved/rejected），与 Phase 18 引擎 target_handle 语义一致（SSOT-02 完成）。
- 前端三套硬编码源中 `portConfig.ts` 渲染路径已退出（仅留 `migratePortId` 兼容）；`TRIGGER_NODE_TYPES` 渲染/判定依赖已清除。
- 19-05（D-05）可重写 `node-sync.test.ts` 为 fixture 驱动、修 `validate-node-definitions.ts` URL，并顺带补 `workflow-data-table.test.ts` 的 pinia setup（见 Deferred）。
## Self-Check: PASSED

- 创建文件存在：`web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts`、`.planning/phases/19-ssot/19-04-SUMMARY.md`、`.planning/phases/19-ssot/deferred-items.md` 均 FOUND
- 任务提交存在：`25381e4d4`、`da0c06c39` 均 FOUND（git cat-file 确认）
- 门禁：`pnpm -C web type-check` exit 0；BaseWorkflowNode.test.ts 4 passed；editor 测试 31 passed；node-sync 5 passed；`migratePortId` 保留、`[id].vue` 无 `TRIGGER_NODE_TYPES`、fetchNodeTypes 先于 fetchWorkflow

---
*Phase: 19-ssot*
*Completed: 2026-06-13*
