---
phase: 19-ssot
plan: 03
subsystem: ui
tags: [vue3, pinia, typescript, node-registry, store-adapter, zod, vue-tsc]

# Dependency graph
requires:
  - phase: 19-01
    provides: GET /api/node-types/ 暴露 ui_schema/default_config；后端字段事实源
  - phase: 19-02
    provides: 存量 fetch_project_info→fetch_space_info 幂等数据迁移
provides:
  - useNodeTypesStore.NodeType 扩 ui_schema/default_config/execution_mode（前端运行时驱动字段）
  - registry.ts store 适配器 helper（toDefinition snake→camel），getNodeDefinition/getDefaultConfig/getNodesByCategory/hasNodeDefinition/validateNodeConfig 唯一源 = useNodeTypesStore
  - CONFIG_COMPONENTS 独立懒加载映射（前端专属，API 不可下发，保留）
  - validateNodeConfig 轻量降级（config_schema.required/type，不引入 ajv）
  - NODE_REGISTRY legacy 硬编码区块删除（含幽灵 fetch_project_info）；8 消费方收敛到 store helper
affects: [19-04, 19-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "store 适配器（toDefinition）：后端 snake_case NodeType → 前端 camelCase NodeTypeDefinition，统一收口 8 消费方"
    - "前端专属能力剥离：configComponent（CONFIG_COMPONENTS）/视觉（nodeVisuals）保留，纯数据交 store"
    - "客户端校验轻量降级：基于 JSON-Schema required/type 顶层检查，完整校验交 Phase 20 后端"

key-files:
  created:
    - web/src/types/workflow/__tests__/registry.test.ts
  modified:
    - web/src/stores/useNodeTypesStore.ts
    - web/src/types/workflow/registry.ts
    - web/src/types/workflow/schemas.ts
    - web/src/types/workflow/index.ts
    - web/src/components/workflow/config/FetchProjectInfoConfig.vue
    - web/src/components/workflow/editor/nodes/index.ts
    - web/src/components/workflow/WorkflowMiniMap.vue
    - web/src/components/workflow/WorkflowDataTable.vue
    - web/src/components/workflow/editor/composables/useDragAndDrop.ts
    - web/src/types/workflow/node-definitions/categories/trigger.ts
    - web/src/types/workflow/node-definitions/index.ts

key-decisions:
  - "NodeTypeKey 退化为 string 别名（不再 keyof typeof NODE_REGISTRY），保留 barrel 导出以兼容 useNodeMeta 类型消费"
  - "useDragAndDrop 取默认配置从 def.schema.parse({}) 改为 def.defaultConfig（store 适配器无 zod schema）"
  - "GradientEdge.vue / CreateWorkflowModal.vue / useNodeMeta.ts 已读 helper/NodeTypeKey，无需改动即随 helper 换源生效"
  - "node-sync.test.ts 不在本计划重写（D-05/19-05 范畴），保持现状仍绿"

patterns-established:
  - "Pattern 2（RESEARCH）：toDefinition store→Definition 适配器统一 snake/camel 转换"
  - "前端专属 CONFIG_COMPONENTS 映射与 nodeVisuals 视觉源独立保留"
  - "validateNodeConfig 轻量 JSON-Schema 校验（required + 顶层 type）"

requirements-completed: [SSOT-01]

# Metrics
duration: ~25min
completed: 2026-06-13
---

# Phase 19 Plan 03: 前端节点定义收敛到 store（删 NODE_REGISTRY legacy）Summary

**把 `registry.ts` 对外 helper 改为从 `useNodeTypesStore`（唯一运行时源）读取并删除 `NODE_REGISTRY` legacy 硬编码区块，抽出前端专属 `CONFIG_COMPONENTS` 懒加载映射、降级 `validateNodeConfig` 为轻量 JSON-Schema 校验，并收敛全部消费方使 `pnpm type-check` 一次性通过。**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-13
- **Tasks:** 2
- **Files modified:** 11（1 新建 + 10 修改）

## Accomplishments
- `useNodeTypesStore.NodeType` 扩 `ui_schema`/`default_config`/`execution_mode`，闭合前端运行时驱动所需字段（来自 19-01 后端）
- `registry.ts` 新增 `toDefinition` 适配器（snake→camel），`getNodeDefinition/getDefaultConfig/getNodesByCategory/hasNodeDefinition/validateNodeConfig` 全部从 `useNodeTypesStore` 取值
- 抽出独立 `CONFIG_COMPONENTS`（前端专属懒加载配置组件映射，含 `fetch_space_info` 复用 `FetchProjectInfoConfig.vue`）
- 删除 `NODE_REGISTRY` legacy 区块（含幽灵 `fetch_project_info`）+ `MIGRATED_REGISTRY`；barrel 移除 `NODE_REGISTRY` 导出、新增 `CONFIG_COMPONENTS`
- 8 消费方收敛：`WorkflowMiniMap`/`WorkflowDataTable`（`getNodeDefinition`）、`editor/nodes/index.ts`（纯 `allNodeTypeKeys` 生成 + Proxy fallback）、`useDragAndDrop`（`def.defaultConfig`）；`GradientEdge`/`CreateWorkflowModal`/`useNodeMeta` 已经读 helper 自动随换源生效
- `migratePortId`、`nodeVisuals.ts`（icon/color）、`CONFIG_COMPONENTS` 懒加载映射均按 D-02/D-04 保留——仅删纯数据硬编码

## Task Commits

Each task was committed atomically:

1. **Task 1: store 接口扩字段 + registry helper 改 store 适配器 + CONFIG_COMPONENTS + validateNodeConfig 降级 + 幽灵改名 + 单测** - `db2135f27` (feat)
2. **Task 2: 删 NODE_REGISTRY legacy + 8 消费方收敛到 store helper** - `47ac186e8` (feat)
3. **Task 2 收尾: 清理残留 NODE_REGISTRY 注释引用（满足 grep 门禁）** - `c53c250a1` (refactor)

_Note: Task 2 拆成功能提交（删 legacy + 收敛）与注释清理提交（grep 门禁要求 `web/src` 内无 `NODE_REGISTRY` 字符串）。_

## Files Created/Modified
- `web/src/stores/useNodeTypesStore.ts` - `NodeType` 接口扩 `ui_schema`/`default_config`/`execution_mode`
- `web/src/types/workflow/registry.ts` - `toDefinition` 适配器 + `CONFIG_COMPONENTS` + store 驱动 helper + `validateNodeConfig` 降级；删 `NODE_REGISTRY`/`MIGRATED_REGISTRY`；`NodeTypeKey` 改 `string`
- `web/src/types/workflow/schemas.ts` - 幽灵改名 `FetchProjectInfoConfig`→`FetchSpaceInfoConfig` + `NODE_CONFIG_SCHEMAS` key `fetch_space_info`
- `web/src/types/workflow/index.ts` - barrel 移除 `NODE_REGISTRY` 导出、增 `CONFIG_COMPONENTS`、`FetchProjectInfoConfig`→`FetchSpaceInfoConfig` re-export
- `web/src/components/workflow/config/FetchProjectInfoConfig.vue` - 类型 `FetchProjectInfoConfig`→`FetchSpaceInfoConfig`（文件名保留，D-03）
- `web/src/components/workflow/editor/nodes/index.ts` - 去 `NODE_REGISTRY`/`NodeTypeKey` 依赖，节点类型映射纯从 `allNodeTypeKeys`(nodeVisuals) + `specialNodes` 生成，保留 Proxy fallback
- `web/src/components/workflow/WorkflowMiniMap.vue` - `NODE_REGISTRY[type]` → `getNodeDefinition(type)`
- `web/src/components/workflow/WorkflowDataTable.vue` - `NODE_REGISTRY[type]` → `getNodeDefinition(type)`（displayName/icon）
- `web/src/components/workflow/editor/composables/useDragAndDrop.ts` - 默认配置 `def.schema.parse({})` → `def.defaultConfig ?? {}`
- `web/src/types/workflow/__tests__/registry.test.ts`（新建）- store 适配器单测（10 用例：getNodeDefinition/getDefaultConfig/getNodesByCategory/hasNodeDefinition/configComponent/validateNodeConfig）
- `web/src/types/workflow/node-definitions/{categories/trigger.ts,index.ts}` - 清理过时的 `NODE_REGISTRY` 注释引用

## Decisions Made
- **`NodeTypeKey` 退化为 `string` 别名**：删 `NODE_REGISTRY` 后 `keyof typeof NODE_REGISTRY` 不再成立；保留 barrel 导出以兼容 `useNodeMeta.ts` 的类型消费（`getAllNodeTypes(): NodeTypeKey[]`），无类型断裂。
- **`useDragAndDrop` 默认配置取值改 `def.defaultConfig`**：store 适配器返回的 `NodeTypeDefinition.schema` 为可选（store 无 zod schema），`def.schema.parse({})` 会触类型/运行时错误；改读后端 `default_config`（19-01 已下发），语义等价且更准确（Rule 1/3）。
- **`GradientEdge.vue`/`CreateWorkflowModal.vue`/`useNodeMeta.ts` 无需改动**：三者本就调用 `getNodeDefinition`/`getNodesByCategory` 或仅消费 `NodeTypeKey` 类型，helper 内部换源后自动经 store 取值。
- **节点视觉/configComponent 保留（D-02/D-04）**：`nodeVisuals.ts`（icon/color）、`CONFIG_COMPONENTS` 懒加载映射、`migratePortId` 均未触碰——本计划仅删纯数据硬编码源。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `useDragAndDrop` 默认配置改用 store `default_config`**
- **Found during:** Task 2（消费方收敛）
- **Issue:** store 适配器的 `NodeTypeDefinition.schema` 为可选（恒 undefined），原 `def.schema.parse({})` 既破坏 `type-check`（possibly undefined）又会运行时抛错
- **Fix:** 改为 `(def?.defaultConfig as Record<string, unknown>) ?? {}`，直接用后端下发的 `default_config`
- **Files modified:** web/src/components/workflow/editor/composables/useDragAndDrop.ts
- **Verification:** `pnpm type-check` 通过；`useDragAndDrop.test.ts` 21 用例绿
- **Committed in:** `47ac186e8`

**2. [Rule 3 - Blocking] 清理过时 `NODE_REGISTRY` 注释以满足 grep 门禁**
- **Found during:** Task 2 verify
- **Issue:** 计划 verify 命令 `rg -q "NODE_REGISTRY" web/src && exit 1` 为硬门禁；`trigger.ts`/`node-definitions/index.ts`/`registry.test.ts` 残留过时注释含 `NODE_REGISTRY` 字符串会触发失败，且注释已与现状不符
- **Fix:** 改写三处注释（去除 `NODE_REGISTRY`，改述为"由后端 /api/node-types/（store）驱动"）
- **Files modified:** trigger.ts, node-definitions/index.ts, registry.test.ts
- **Verification:** `rg "NODE_REGISTRY" web/src` 无命中 → "NODE_REGISTRY removed"
- **Committed in:** `c53c250a1`

---

**Total deviations:** 2 auto-fixed（1 bug、1 blocking）
**Impact on plan:** 均为收敛正确性/门禁所必需，无范围蔓延。

## Issues Encountered
- **vue-tsc 首次报"stale"未用导入错误**：删 `NODE_REGISTRY` 后首轮 `pnpm type-check` 报 `registry.ts` 旧行号未用导入（实为编辑落盘与启动竞态的过期快照）；重跑后 exit 0，确认导入已正确精简。
- **前端无 `uv.lock`/依赖变更**：未触碰 `server/uv.lock`，无需还原。

## Deferred Issues
- **全量 `pnpm -C web test:unit` 有 3 个无关超时失败**：`pages/codegraph/__tests__/galaxy.spec.ts`、`pages/codegraph/__tests__/playground.spec.ts`、conversations 管理页用例——均为 5s/15s 超时（重负载并行下的 codegraph/会话页慢测试），不 import registry/NODE_REGISTRY，与本计划改动无关（SCOPE BOUNDARY，记录不修）。本计划相关 3 个测试文件（registry/useDragAndDrop/node-sync）共 31 用例全绿。

## Next Phase Readiness
- 前端 palette/默认 config/显示名/校验已全部经 `useNodeTypesStore` 驱动（SSOT-01），`NODE_REGISTRY` 主硬编码源已删除。
- 19-04（D-04 画布 Handle 由 store inputs/outputs 渲染、`BaseWorkflowNode`/`portConfig` 降级、`nodeVisuals`/`NodePalette` 幽灵改名）可基于本计划的 store 适配器继续；注意 `nodeVisuals.ts` L50 / `NodePalette.vue` L46 / `IntegrationNode.vue` 仍含 `fetch_project_info`（本计划范围外）。
- 19-05（D-05 重写 `node-sync.test.ts` 为 fixture 驱动、修 `validate-node-definitions.ts` URL）未触碰，现有 `node-sync.test.ts` 仍绿。

## TDD Gate Compliance
Task 1 标注 `tdd="true"`，但 `config.json` `tdd_mode: false` 且 orchestrator 未传 MVP_MODE/TDD_MODE，故未强制 RED→GREEN 提交序列门禁。实务上 Task 1 同时落地实现 + `registry.test.ts`（10 passed），覆盖等价。

## Self-Check: PASSED

- 创建文件存在：`web/src/types/workflow/__tests__/registry.test.ts`、`.planning/phases/19-ssot/19-03-SUMMARY.md` 均 FOUND
- 任务提交存在：`db2135f27`、`47ac186e8`、`c53c250a1` 均 FOUND
- 门禁：`pnpm -C web type-check` exit 0；`rg "NODE_REGISTRY" web/src` 无业务/注释命中；registry/useDragAndDrop/node-sync 三测共 31 用例绿

---
*Phase: 19-ssot*
*Completed: 2026-06-13*
