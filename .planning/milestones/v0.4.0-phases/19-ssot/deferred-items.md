# Phase 19 — Deferred Items

> Out-of-scope discoveries logged during execution. Not fixed (SCOPE BOUNDARY).

## 19-04
- status: acknowledged


- **`web/src/components/__tests__/workflow-data-table.test.ts` 2 用例失败（pre-existing, 非本计划文件）**
  - 现象：`getActivePinia() was called but there was no active Pinia` —— `WorkflowDataTable.vue` → `getNodeTypeCounts` → `registry.getNodeDefinition()` → `useNodeTypesStore()`，但该测试未 `setActivePinia`。
  - 根因：19-03 把 `registry.getNodeDefinition` 改为运行时读 `useNodeTypesStore`（store 适配器），而 `workflow-data-table.test.ts` 未随之补 pinia setup（19-03 仅跑了 registry/useDragAndDrop/node-sync 三测）。
  - 与 19-04 无关：本计划仅改 `BaseWorkflowNode.vue`/`portConfig.ts`/`[id].vue`/`useWorkflowsStore.ts` + 新增 `BaseWorkflowNode.test.ts`，未触碰 `WorkflowDataTable.vue` 或其测试。
  - 建议：在 `workflow-data-table.test.ts` 顶部 `setActivePinia(createPinia())`（或 `createTestingPinia`）即可修复；归 19-05（D-05 测试体系）或单独补测处理。

## 19-05
- status: acknowledged


- **[已解决] `workflow-data-table.test.ts` 缺 pinia 回归**
  - 19-05 已按上方建议补 `beforeEach(() => setActivePinia(createPinia()))`，3 用例全绿。提交 `51a2c25d2`。

- **`pnpm -C web lint` 全量存在 pre-existing 失败（非本计划文件，SCOPE BOUNDARY 不修）**
  - `web/.pytest_cache/README.md`：1 个 `format/prettier` error。该路径 gitignored（`git check-ignore` 命中），为 pytest 生成的临时缓存文件，eslint 扫描到但不应纳入；非源代码。
  - `web/src/components/repository/AISummarySection.vue`：4 个 `vue/singleline-html-element-content-newline` warning。该文件最近由 `24fc2fec1`（仓库管理 UI）引入，与本计划无关。
  - 本计划改动的 8 个文件单独 `eslint` 均零问题；`pnpm type-check` 全绿。
