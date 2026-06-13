---
phase: 19-ssot
plan: 05
subsystem: ui
tags: [vue3, vitest, fixture, node-registry, drift-guard, pinia, ssot]

# Dependency graph
requires:
  - phase: 19-01
    provides: 离线 node-types.fixture.json（33 节点精简快照，含 fetch_space_info、无幽灵）+ gen:node-fixture 命令
  - phase: 19-03
    provides: registry helper 收敛到 useNodeTypesStore；CONFIG_COMPONENTS（fetch_space_info→FetchProjectInfoConfig.vue）
provides:
  - 前端展示层（nodeVisuals/NodePalette）幽灵 fetch_project_info 全量改名 fetch_space_info（D-03 闭环）
  - 死代码 IntegrationNode.vue 删除（A2 核实仅 components.d.ts 命中）
  - node-sync.test.ts fixture 驱动漂移守护（删手维 EXPECTED_NODES，palette ⊆ fixture、无幽灵、多端口对 fixture 校验）
  - validate-node-definitions.ts API URL 修正 /api/node-types/（D-05）
  - workflow-data-table.test.ts pinia 回归修复（19-03 store 化引入）
affects: [phase-20-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "离线 fixture 驱动漂移守护：测试 import 后端入库 fixture，断言 palette types ⊆ fixture node_type 全集（CI 不起后端）"
    - "正则提取 palette 节点前先剥离注释，避免文档示例（type:'xxx'）被误判为节点类型"

key-files:
  created: []
  modified:
    - web/src/components/workflow/editor/nodes/nodeVisuals.ts
    - web/src/components/workflow/sidebar/NodePalette.vue
    - web/src/components.d.ts
    - web/src/components/__tests__/node-sync.test.ts
    - web/scripts/validate-node-definitions.ts
    - web/src/components/__tests__/validate-nodes.test.ts
    - web/src/components/__tests__/workflow-data-table.test.ts
  deleted:
    - web/src/components/workflow/editor/nodes/IntegrationNode.vue

key-decisions:
  - "node-sync 的 parallel/join 多端口断言改对 fixture 真实多输出节点（ai_plan_approval approved/rejected、webhook_trigger）校验——fixture 中 parallel.outputs/join.inputs 为空（运行时动态端口），无法对其做 ≥2 断言"
  - "rewritten node-sync 不写 'fetch_project_info' 字面量——幽灵缺席由 palette ⊆ fixture 泛化保证，满足全仓前端源零残留 grep 门禁"
  - "IntegrationNode.vue 删除后 components.d.ts 手动移除孤儿声明行（vue-tsc --noEmit 不触发 unplugin 重生成，dev/vitest 的 watcher 也仅对 live unlink 事件响应）"

patterns-established:
  - "Pattern: fixture 驱动 CI 漂移守护——palette ⊆ fixture ∧ 无幽灵 ∧ 真实节点在；失败信息指向 gen:node-fixture（Pitfall 6）"
  - "Pattern: store 化组件单测必须 setActivePinia(createPinia())（19-03 起 getNodeDefinition 运行时读 store）"

requirements-completed: [SSOT-03, SSOT-01]

# Metrics
duration: ~12min
completed: 2026-06-13
---

# Phase 19 Plan 05: 幽灵前端改名收尾 + 死代码清理 + fixture 驱动漂移守护 Summary

**前端展示层 `fetch_project_info` 全量改名 `fetch_space_info`、删除死代码 `IntegrationNode.vue`，并把 `node-sync.test.ts` 从手维 `EXPECTED_NODES` 重写为 fixture 驱动离线漂移守护、修正 `validate-node-definitions.ts` 的 API URL，同时修复 19-03 引入的 `workflow-data-table.test.ts` 缺 pinia 回归。**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-13
- **Tasks:** 2（+1 回归修复）
- **Files modified:** 7 改 + 1 删

## Accomplishments
- `nodeVisuals.ts` / `NodePalette.vue` 的运行时 type `fetch_project_info` → `fetch_space_info`，前端"幽灵消失、真实节点出现"在展示层闭环（D-03）
- 核实 `IntegrationNode.vue` 仅被自动生成的 `components.d.ts` 命中、`editor/nodes/index.ts` 未映射 → 判定死代码并删除，同步清理孤儿声明
- 重写 `node-sync.test.ts` 为 fixture 驱动：import `node-types.fixture.json`，断言 palette ⊆ fixture 全集、已根除幽灵不在 palette、`fetch_space_info` 在、多端口节点端口集对 fixture 校验；失败信息指向 `gen:node-fixture`（Pitfall 6）
- 修正 `validate-node-definitions.ts` 错误 URL `/api/workflows/node-types/` → `/api/node-types/`，并在 `validate-nodes.test.ts` 加严断言（含 `/api/node-types/`、不含 `workflows/node-types`）
- 修复本阶段（19-03）引入的回归：`workflow-data-table.test.ts` 补 `setActivePinia(createPinia())`，3 用例转绿

## Task Commits

Each task was committed atomically:

1. **Task 1: 幽灵改名 + 删死代码 IntegrationNode** - `4bedb1d16` (refactor)
2. **Task 2: node-sync fixture 驱动 + validate URL 修正 + 断言加严** - `8f7462b70` (test)
3. **回归修复: workflow-data-table 缺 pinia** - `51a2c25d2` (test)

## Files Created/Modified
- `web/src/components/workflow/editor/nodes/nodeVisuals.ts` - 视觉键 `fetch_project_info`→`fetch_space_info`
- `web/src/components/workflow/sidebar/NodePalette.vue` - palette 项改名（保留"数据获取"展示组，Pitfall 2）
- `web/src/components/workflow/editor/nodes/IntegrationNode.vue` - **删除**（死代码，A2 核实）
- `web/src/components.d.ts` - 移除已删组件的 unplugin 自动声明行
- `web/src/components/__tests__/node-sync.test.ts` - 删 `EXPECTED_NODES`，改 fixture 驱动对账（剥离注释防误判）
- `web/scripts/validate-node-definitions.ts` - API URL 修正为 `/api/node-types/`
- `web/src/components/__tests__/validate-nodes.test.ts` - 加严：含 `/api/node-types/` 且不含 `workflows/node-types`
- `web/src/components/__tests__/workflow-data-table.test.ts` - 补 pinia setup（回归修复）

## Decisions Made
- **parallel/join 多端口断言改对 fixture 真实多输出节点**：fixture（后端 NodeRegistry 静态 dump）中 `parallel.outputs=[]`、`join.inputs=[]`（这两类节点的分支端口是运行时动态生成），无法对其做"≥2 端口"断言。改为：断言 parallel/join 作为 `control` 节点存在于 fixture，并对真正含静态多端口的节点（`ai_plan_approval` 的 approved/rejected、`webhook_trigger` 多输出）做端口集漂移守护——既去除对 `getDefaultPortsForNodeType` 的依赖，又保留多端口守护价值。
- **rewritten test 不写 `fetch_project_info` 字面量**：用户成功标准要求"全仓前端源零残留 `fetch_project_info`"。幽灵缺席改由 `palette ⊆ fixture`（fixture 无该 type，若 palette 含则 ⊆ 断言即失败）泛化保证；显式字面量仅保留对从未真实存在的 `code_implement`/`technical_plan` 的守护。
- **components.d.ts 手动移除孤儿行**：`pnpm type-check`(`vue-tsc --noEmit`) 不跑 vite 插件、不会重生成 dts；dev/vitest 的 unplugin watcher 仅对 live add/unlink 事件响应（删文件早于 server 启动则不触发）。直接移除单行孤儿声明与重生成结果等价且确定，type-check 随后零错。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] node-sync 多端口断言对齐 fixture 实况（parallel/join 静态端口为空）**
- **Found during:** Task 2
- **Issue:** 计划契约 ④ 要求"parallel/join 多端口对 fixture 端口集断言"，但 fixture 中 parallel/join 的动态分支端口为空（`parallel.outputs=[]`、`join.inputs=[]`），照字面断言会写出恒假/破碎测试
- **Fix:** parallel/join 改断言其作为 control 节点存在于 fixture；多端口守护移到 fixture 中真正含静态多端口的节点（ai_plan_approval、webhook_trigger）
- **Files modified:** web/src/components/__tests__/node-sync.test.ts
- **Verification:** node-sync 5 用例全绿
- **Committed in:** `8f7462b70`

**2. [Rule 3 - Blocking] node-sync 正则误判注释中的 `type: 'xxx'`**
- **Found during:** Task 2（首跑 ⊆ 断言失败，orphan=['xxx']）
- **Issue:** NodePalette.vue 文档注释含示例 `type: 'xxx'`，被 palette 提取正则当作节点类型，导致 ⊆ fixture 断言失败（旧测试从不枚举全集故未暴露）
- **Fix:** 提取前剥离 `<!-- -->`/`/* */`/`//` 注释；production 文件不改
- **Files modified:** web/src/components/__tests__/node-sync.test.ts
- **Verification:** ⊆ 断言通过；node-sync/validate-nodes 共 10 用例全绿
- **Committed in:** `8f7462b70`

**3. [Rule 1 - Bug] workflow-data-table.test.ts 缺 pinia 回归（19-03 引入，用户指定本计划修复）**
- **Found during:** 回归修复阶段
- **Issue:** 19-03 把 `WorkflowDataTable.vue` 经 `getNodeDefinition` 改读 `useNodeTypesStore`，但该测试未 `setActivePinia`，mount 抛 `getActivePinia() was called but there was no active Pinia`
- **Fix:** 补 `beforeEach(() => setActivePinia(createPinia()))`（store 留空，芯片名/图标走 type 回退）
- **Files modified:** web/src/components/__tests__/workflow-data-table.test.ts
- **Verification:** 3 用例全绿
- **Committed in:** `51a2c25d2`

---

**Total deviations:** 3 auto-fixed（2 bug、1 blocking）
**Impact on plan:** 均为契约与 fixture 实况对齐 / 门禁阻塞 / 用户指定回归，无范围蔓延。

## Issues Encountered
- `components.d.ts` 未被 dev/vitest 自动重生成（见 Decisions），手动移除孤儿声明行后 type-check 零错。

## Deferred Issues
- **`pnpm -C web lint` 全量有 pre-existing 失败（SCOPE BOUNDARY，未修）**：`web/.pytest_cache/README.md`（1 error，gitignored 临时缓存）、`web/src/components/repository/AISummarySection.vue`（4 warning，由无关提交 `24fc2fec1` 引入）。本计划改动的 8 个文件单独 eslint 零问题，`pnpm type-check` 全绿。已记入 `deferred-items.md`。
- **全量 vitest 既有 3 个无关超时失败**（codegraph galaxy/playground、conversations 慢测）——非本计划职责（任务说明已注明），不在本计划处理。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- D-03 幽灵改名已全链路收尾（后端 19-02 数据迁移 + 前端展示层）；D-05 漂移守护已在 CI（离线 vitest）生效。
- Phase 20 校验前移（VAL-01/02/03）可基于现有 store 适配器与 fixture 守护继续；注意（Pitfall 6）改后端节点定义后须重跑 `pnpm -C web gen:node-fixture` 刷新 fixture。

## Self-Check: PASSED

- 修改/新建文件存在：`node-sync.test.ts`、`validate-node-definitions.ts`、`validate-nodes.test.ts`、`workflow-data-table.test.ts`、`19-05-SUMMARY.md` 均 FOUND
- 删除生效：`IntegrationNode.vue` 已删除（DELETED-OK）
- 任务提交存在：`4bedb1d16`、`8f7462b70`、`51a2c25d2` 均 FOUND
- 门禁：`pnpm -C web type-check` exit 0；node-sync/validate-nodes/workflow-data-table/registry 共 23 用例全绿；`rg fetch_project_info web/src` 零命中

---
*Phase: 19-ssot*
*Completed: 2026-06-13*
