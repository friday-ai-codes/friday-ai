---
phase: 93-capability-slot-editor
plan: 06
subsystem: ui
tags: [vue, vue-flow, workflow-editor, slot, snap, attach-group, connection]

# Dependency graph
requires:
  - phase: 93-capability-slot-editor
    provides: "93-01 portShapes/getValidationError 契约校验 + 93-02 useConnectionDragState/usePortSnap 磁吸共享逻辑 + 93-03 store attachChild/detachChild/getChildNodes + transform parentNode 映射"
provides:
  - "WorkflowCanvas 画布层 SLOT-03/04 集成：@connect-start/@connect-end 驱动共享拖拽态、@pointermove 吸附端点（snap-locked）、onConnect 不兼容拒绝 Toast + 吸附目标端口落点"
  - "clarify 槽连澄清卡 → store.attachChild 形成附着编组（非普通边）；删父级联删子确认 + 右键解除附着确认"
  - "附着编组容器单一实现（WARNING 2 收敛）：.slot-attach-group 琥珀虚线容器（随 viewport 平移缩放）+ .slot-attach-connector 短实线琥珀连接器（≤24px），稳定 hook 供 vitest 断言"
  - "CustomConnectionLine 可选 snapX/snapY：命中吸附用吸附端点绘制 bezier + emerald 脉冲（prefers-reduced-motion 降级）"
affects: [94-entry-unification, capability-slot-editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "画布层经 defineExpose 暴露内部处理器（onConnect/updateSnapFromPointer/attachGroups/pending*）供单测直驱，规避真实 @vue-flow 交互不可测"
    - "附着编组容器派生 computed（getChildNodes 聚合 + findNode 几何 best-effort，happy-dom 无布局时尺寸 0 但元素必存在），不每帧建新对象"
    - "吸附候选 compatible 由 isCompatibleTarget 预标注 → findSnapTarget 仅吸兼容候选（吸附不放行不兼容）；落点仍经 getValidationError 双校验"

key-files:
  created:
    - web/src/components/workflow/editor/__tests__/WorkflowCanvas.slot.test.ts
  modified:
    - web/src/components/workflow/editor/WorkflowCanvas.vue
    - web/src/components/workflow/editor/edges/CustomConnectionLine.vue

key-decisions:
  - "吸附目标端口在 onConnect 顶部用 snapTarget 覆盖 connection.target/targetHandle，再走 getValidationError 双校验 + addEdge（吸附改落点不绕合法性）"
  - "解除附着触发用 @node-context-menu（右键）而非改 BaseWorkflowNode 工具栏——全部逻辑收敛在 WorkflowCanvas 单文件，零跨文件耦合"
  - "附着编组渲染由 store 父子数据（getChildNodes）驱动而非依赖 Vue Flow 实时几何，保证无布局环境（测试）也能存在性断言"
  - "删父确认用延后删模式：onNodesChange remove 时若有附着子则置 pendingDelete 不立即 removeNode（受控 :nodes 故节点保留），确认后才级联删"

patterns-established:
  - "画布交互处理器 defineExpose + @vue-flow 系包/重组件 stub 的可测面范式（useVueFlow mock 提供 viewport/getNodes/findNode/getEdges/screenToFlowCoordinate）"
  - "AlertDialog 确认收口在 WorkflowCanvas（pendingDelete/pendingDetach ref + confirm/cancel），文案读 93-01 已落 i18n 键，不写 locale"

requirements-completed: [SLOT-03, SLOT-04]

# Metrics
duration: ~22min
completed: 2026-06-27
---

# Phase 93 Plan 06: 画布磁吸交互 + 附着编组渲染 Summary

**WorkflowCanvas 画布层兑现 SLOT-03 磁吸（@connect-start/end 驱动共享拖拽态 + 吸附端点 snap-locked + 不兼容拒绝 Toast，吸附不绕合法性）与 SLOT-04 附着编组（clarify 连澄清卡 → attachChild、单一实现 .slot-attach-group 琥珀虚线容器 + .slot-attach-connector 连接器、删父级联删子确认 + 右键解除附着确认），既有连线/拖拽/snap-grid 零回归。**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-27T13:24:00Z
- **Completed:** 2026-06-27T13:46:00Z
- **Tasks:** 2 自治代码任务（+ 1 human-verify checkpoint 延后到 phase UAT）
- **Files modified:** 3（2 改 + 1 新增测试）

## Accomplishments

- **SLOT-03 磁吸交互闭环（Task 1）**：`WorkflowCanvas` 接 `@connect-start`/`@connect-end` → 解析源 output shape（`resolvePortShape`）→ `useConnectionDragState.startConnect/endConnect` 驱动共享拖拽态；`@pointermove` 收集可见节点 input handle 几何（`getNodes` + `findNode` + 节点类型 inputs）并经 `isCompatibleTarget` 标注兼容 → `findSnapTarget` 算吸附端点（仅吸兼容候选）；`onConnect` 命中吸附用吸附目标端口落点，落点仍经 `getValidationError` 双校验，不兼容弹 `incompatibleTitle`/`incompatibleBody` Toast 拒绝。
- **CustomConnectionLine 吸附端点（Task 1）**：新增可选 `snapX`/`snapY`（flow 坐标），命中时用吸附端点绘制 bezier 终点 + emerald 实心圆 + `snap-pulse` 脉冲环（`@media (prefers-reduced-motion: reduce)` 降级为静态）；未命中保留既有落点小竖条（零回归）。
- **SLOT-04 附着编组（Task 2）**：`onConnect` 检测方案节点 clarify 槽（`shape=clarification_request`）连 `clarification_card` → `store.attachChild`（绝对→相对换算 + dock 右下偏移），不建普通边；**附着编组容器单一实现（WARNING 2 收敛）**——派生 `attachGroups` computed 对每个有附着子的父节点输出一个 `.slot-attach-group`（`bg-amber-500/[0.04] border border-dashed border-amber-400/40 rounded-2xl`，随 viewport transform）+ 一个 `.slot-attach-connector`（短实线琥珀，24px）。
- **级联删除 / 解除附着确认（Task 2）**：删带附着子的方案节点前弹 `deleteWithChildBody` AlertDialog（延后删，确认后 `store.removeNode` 级联删子），无子节点直接删（零回归）；子节点右键 `@node-context-menu` → `detachTitle`/`detachBody` 确认 → `store.detachChild`（相对→绝对恢复独立坐标）。

## Task Commits

Each task was committed atomically:

1. **Task 1: 画布磁吸交互 + 吸附端点 + 不兼容拒绝 Toast（SLOT-03）** - `7020338c9` (feat)
2. **Task 2: 附着编组渲染 + clarify 附着 + 级联删除/解除确认（SLOT-04）** - `394cff119` (feat)

**Plan metadata:** (final docs commit — see below)

_无 TDD 拆分，每个 task 含实现 + 单测一次提交。_

## Files Created/Modified

- `web/src/components/workflow/editor/WorkflowCanvas.vue` - 接 connect-start/end + pointermove 吸附 + onConnect 吸附落点/不兼容 Toast/clarify 附着 + 附着编组 overlay 渲染 + 删父级联/解除附着 AlertDialog 确认；defineExpose 可测面。
- `web/src/components/workflow/editor/edges/CustomConnectionLine.vue` - 新增 snapX/snapY，命中吸附用吸附端点绘制 + snap-locked emerald 脉冲（reduced-motion 降级）。
- `web/src/components/workflow/editor/__tests__/WorkflowCanvas.slot.test.ts` - SLOT-03/04 画布层集成单测（@vue-flow 系包 stub + useVueFlow mock + defineExpose 直驱），12 例全绿。

## Decisions Made

- **吸附落点覆盖在 onConnect 顶部 + 双校验保留**：`snapTarget` 命中时覆盖 `connection.target/targetHandle` 后仍走 `getValidationError`（吸附改视觉/落点端口，绝不绕过合法性，缓解 T-93-06-BYPASS）。
- **解除附着用右键 `@node-context-menu`**：避免改 `BaseWorkflowNode`（plan files_modified 仅含 WorkflowCanvas + CustomConnectionLine + test），全部 detach 逻辑收敛单文件。
- **附着编组渲染 store 数据驱动**：`attachGroups` 由 `getChildNodes` 父子关系派生（findNode 几何 best-effort 补包围盒），happy-dom 无真实布局时尺寸为 0 但元素必渲染存在（满足最小 vitest 存在性断言）。
- **删父延后删模式**：受控 `:nodes` 下 `onNodesChange` remove 时若有附着子则置 `pendingDelete` 不立即 `removeNode`，节点保留至 AlertDialog 确认后级联删（取消则保留）。

## Deviations from Plan

None - plan executed exactly as written.

（说明：吸附候选 handle 几何采用「节点左缘 + 卡高度内均匀分布」近似，real runtime 由 Vue Flow `computedPosition/dimensions` 提供精确值；plan 已授权 happy-dom 无布局时尺寸可为 0，属实现细节非偏离。）

## Issues Encountered

- `findNode().computedPosition` 类型为 `XYZPosition`（含 z），`nodeBox` 回退分支返回 `{x,y}` 触发 vue-tsc TS2322/TS18048 → 改为显式提取 `cp.x`/`cp.y` 数值并分支赋值，类型转绿。
- `onConnectStart` 入参类型最初未声明 `handleType`，测试透传 VueFlow 真实负载触发 TS2353 → 入参类型补 `handleType?: string | null`（对齐 VueFlow `@connect-start` 负载）。
- `eslint` prefer-nullish-coalescing（CustomConnectionLine endX/endY 三元 → `??`）+ 类型导入排序（`--fix` 归位），受改文件最终干净。

## Human-Verify Checkpoint（延后到 phase UAT 的可视验收项）

本 plan 末含一个 `checkpoint:human-verify`（纯画布交互观感，`autonomous:false`）。当前为自治里程碑执行（inline 全自动），**已完成全部自动化代码任务**，该可视验收项延后到 Phase 93 UAT 由人工浏览器核对，不阻塞收尾：

1. `/workflows/<id>` 编辑器：从节点库拖入「澄清卡」（AI 分组）确认可见可拖。
2. 拖 `ai_plan_research` → 从 `clarify` 琥珀方槽拖向澄清卡 input：兼容槽绿色高亮放大 + 靠近吸附；落下形成琥珀虚线编组（`.slot-attach-group`）+ 子卡『附着』徽标。
3. 不兼容 typed shape 端口互连：高亮禁止 + 落点弹「形状不兼容」Toast，不建边。
4. 删除该方案节点：弹「将一并移除 N 个附着澄清节点」确认；确认后澄清子节点一并消失。
5. 子澄清卡 `feishu_message` 出口拉线到飞书通知节点：应可连。
6. 既有工作流编辑/连线/单选卡：确认零回归（既有模板正常渲染/保存）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SLOT-03/04 用户可见兑现完成：画布磁吸（兼容高亮数据源 + 吸附端点 + 不兼容 Toast 拒绝）+ 附着编组（clarify 附着 + 琥珀虚线容器/连接器 + 删父级联确认 + 右键解除确认）。
- 既有 WorkflowCanvas/连线/对齐/snap-grid(SNAP_THRESHOLD=5) 零回归（editor 全组 91 vitest 全绿）。
- Phase 93（插槽编辑器前端）7 plan（00–06）全部就绪；human-verify 可视验收项记入待 Phase 93 UAT。下游 → Phase 94（入口统一）。

## Self-Check: PASSED

- FOUND: web/src/components/workflow/editor/WorkflowCanvas.vue
- FOUND: web/src/components/workflow/editor/edges/CustomConnectionLine.vue
- FOUND: web/src/components/workflow/editor/__tests__/WorkflowCanvas.slot.test.ts
- FOUND: commit 7020338c9 (Task 1)
- FOUND: commit 394cff119 (Task 2)

---
*Phase: 93-capability-slot-editor*
*Completed: 2026-06-27*
