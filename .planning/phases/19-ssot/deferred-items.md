# Phase 19 — Deferred Items

> Out-of-scope discoveries logged during execution. Not fixed (SCOPE BOUNDARY).

## 19-04

- **`web/src/components/__tests__/workflow-data-table.test.ts` 2 用例失败（pre-existing, 非本计划文件）**
  - 现象：`getActivePinia() was called but there was no active Pinia` —— `WorkflowDataTable.vue` → `getNodeTypeCounts` → `registry.getNodeDefinition()` → `useNodeTypesStore()`，但该测试未 `setActivePinia`。
  - 根因：19-03 把 `registry.getNodeDefinition` 改为运行时读 `useNodeTypesStore`（store 适配器），而 `workflow-data-table.test.ts` 未随之补 pinia setup（19-03 仅跑了 registry/useDragAndDrop/node-sync 三测）。
  - 与 19-04 无关：本计划仅改 `BaseWorkflowNode.vue`/`portConfig.ts`/`[id].vue`/`useWorkflowsStore.ts` + 新增 `BaseWorkflowNode.test.ts`，未触碰 `WorkflowDataTable.vue` 或其测试。
  - 建议：在 `workflow-data-table.test.ts` 顶部 `setActivePinia(createPinia())`（或 `createTestingPinia`）即可修复；归 19-05（D-05 测试体系）或单独补测处理。
