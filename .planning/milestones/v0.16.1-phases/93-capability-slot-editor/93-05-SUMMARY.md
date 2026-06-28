---
phase: 93-capability-slot-editor
plan: 05
subsystem: ui
tags: [vue, vue-flow, workflow-editor, port-shape, slot, drag-state, im-gating, attached-badge, i18n]

# Dependency graph
requires:
  - phase: 93-capability-slot-editor
    provides: "93-01 portShapes（shape 字段 + SHAPE_DISPLAY_KEY）+ NodePort.shape?:string"
  - phase: 93-capability-slot-editor
    provides: "93-02 useConnectionDragState（dragging + isCompatibleTarget，compatible-highlight 数据源）"
  - phase: 93-capability-slot-editor
    provides: "93-03 数据契约：data.metadata.parentNodeId 同源（附着徽标读取来源）"
  - phase: 93-capability-slot-editor
    provides: "93-01 zh-CN.json workflow.editor.slot.* 全量键（imGatedHint/attachedHint/attachedBadge）"
provides:
  - "useImCapability.ts：图级 IM 能力判定（IM_SOURCE_TYPES/IM_DEPENDENT_TYPES + hasImCapability + isImGated）"
  - "BaseWorkflowNode：typed shape 端口圆角方形（input 凹槽描边/output 凸点实心）+ SHAPE_DOT_COLOR 着色（shape 优先，空回退语义色圆形）"
  - "BaseWorkflowNode：拖拽态 input handle compatible-highlight（放大+emerald 光环）/ forbidden（降透明+not-allowed）"
  - "BaseWorkflowNode：IM 门控（缺 chat_id 源 → opacity-40 + 锁徽标 + imGatedHint tooltip）+ 附着徽标（读 data.metadata.parentNodeId + attachedHint）"
affects: [93-06, capability-slot-editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯派生图级能力判定 composable（只读 store.nodes，无副作用/日志），视觉门控由消费组件负责"
    - "handle 形状/着色 O(1) 查表（SHAPE_DOT_COLOR），shape 非空优先、空回退既有 PORT_DOT_COLOR 语义色（圆形零回归命门）"
    - "拖拽态类由模块级单例 useConnectionDragState 驱动（idle 不加类，零回归既有外观）"
    - "附着徽标读取来源固定 data.metadata.parentNodeId（93-03 跨 plan 数据契约同源字段，单测断言来源）"

key-files:
  created:
    - web/src/components/workflow/editor/composables/useImCapability.ts
    - web/src/components/workflow/editor/composables/__tests__/useImCapability.test.ts
    - web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.slot.test.ts
  modified:
    - web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue
    - web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts

key-decisions:
  - "handleColor 对未知 shape（非 SHAPE_DOT_COLOR 映射）回退 PORT_DOT_COLOR[portKind(id)]，防 backgroundColor undefined"
  - "shape 方形/着色经 inline style（borderRadius:4px + border/background），拖拽态/门控经 class + scoped <style>，避免覆盖 vue-flow 默认 handle CSS（inline > stylesheet）"
  - "既有 BaseWorkflowNode.test.ts 补 i18n plugin（组件新增 useI18n 依赖），属测试基础设施适配非行为回归"

patterns-established:
  - "图级 IM 能力判定 = 存在 create_group_chat/create_work_item_chat → 有 chat_id 源；缺源时 IM 依赖节点视觉门控（前端引导，后端执行期仍校验）"
  - "节点卡端口双形状语言：方形=能力契约槽（shape 着色）/ 圆形=通用流（语义色），一眼区分"

requirements-completed: [SLOT-03, SLOT-04]

# Metrics
duration: ~9min
completed: 2026-06-27
---

# Phase 93 Plan 05: 节点卡插槽视觉（端口形状/着色 + 拖拽态 + IM 门控 + 附着徽标）Summary

**BaseWorkflowNode 一次性落地全部节点卡层面插槽视觉：typed shape 端口圆角方形（input 凹槽描边/output 凸点实心）+ shape 色板着色（空回退语义色圆形零回归）、拖拽态兼容 input handle 高亮放大/不兼容降透明、缺 chat_id 源 IM 门控锁徽标 + 引导 tooltip、附着子节点徽标读 data.metadata.parentNodeId；新建纯派生图级 IM 能力判定 composable。**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-27T13:10:29Z
- **Completed:** 2026-06-27T13:19:25Z
- **Tasks:** 2
- **Files modified:** 5（created 3 + modified 2）

## Accomplishments
- 新建 `useImCapability.ts`：`IM_SOURCE_TYPES`（create_group_chat/create_work_item_chat）+ `IM_DEPENDENT_TYPES`（notify_feishu/notify_feishu_im）+ `hasImCapability`（computed：图中存在任一 IM 源）+ `isImGated(nodeType)`（依赖 chat_id 且无源 → true），纯派生只读 store.nodes、无副作用/日志。
- `BaseWorkflowNode` 端口形状/着色：`ports` computed 并入 `shape`；新增 `SHAPE_DOT_COLOR` 色板 + `handleColor`（shape 非空优先、空回退 `PORT_DOT_COLOR[portKind(id)]`）；typed shape input → 圆角方形描边凹槽（透明底）、output → 圆角方形实心凸点；空契约 default/error 保持既有圆形 + 语义色（零回归）。
- 拖拽态（消费 `useConnectionDragState`）：input handle 在 `dragging` 时按 `isCompatibleTarget` 加 `compatible-highlight`（14px + emerald 4px 光环）或 `forbidden`（opacity 0.3 + not-allowed）；idle 不加类零回归。
- IM 门控（消费 `useImCapability`）：`isImGated(props.data.nodeType)` 为 true → 卡片 `opacity-40` + 右上角 `icon-[lucide--lock]` 锁徽标 + `imGatedHint` 引导 tooltip + IM handle `cursor-not-allowed`，不阻断既有交互逻辑。
- 附着徽标（SLOT-04）：读取来源**固定** `props.data.metadata.parentNodeId`（93-03 同源契约），非空 → 左上角琥珀 `附着` Badge + `attachedHint` tooltip。
- i18n 经组件内 `useI18n().t` 读 93-01 已落 `workflow.editor.slot.*` 键（本 plan 不写 locale）。

## Task Commits

Each task was committed atomically:

1. **Task 1: useImCapability 图级 IM 能力判定** - `2be8f2b13` (feat)
2. **Task 2: BaseWorkflowNode 端口形状/着色 + 拖拽态 + IM 门控 + 附着徽标** - `849959d31` (feat)

**Plan metadata:** (final docs commit — see below)

_无 TDD 拆分，每个 task 含实现 + 单测一次提交。_

## Files Created/Modified
- `web/src/components/workflow/editor/composables/useImCapability.ts` - 图级 IM 能力判定（源/依赖集 + hasImCapability + isImGated 纯派生）。
- `web/src/components/workflow/editor/composables/__tests__/useImCapability.test.ts` - 有源/无源/非 IM 节点/响应式/导出集单测（6 例）。
- `web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue` - 端口 shape 方形/圆形 + SHAPE_DOT_COLOR 着色 + 拖拽态类 + IM 门控锁徽标 + 附着徽标 + scoped 拖拽态 CSS。
- `web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.slot.test.ts` - shape 方形/圆形+着色、拖拽 compatible/forbidden、IM 门控锁徽标+文案、附着徽标读 data.metadata.parentNodeId 单测（7 例）。
- `web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts` - 既有 Handle 渲染测试补 i18n plugin（组件新增 useI18n 依赖，零行为回归）。

## Decisions Made
- `handleColor` 对 shape 非空但不在 `SHAPE_DOT_COLOR` 映射的取值回退 `PORT_DOT_COLOR[portKind(id)]`，避免 `backgroundColor: undefined`。
- shape 方形与着色用 inline style（`borderRadius:4px` + `border`/`background`/`backgroundColor`），拖拽态高亮/禁止 + 门控 cursor 用 class + scoped `<style>`——inline style 覆盖 vue-flow 默认 handle 圆角 CSS（inline > stylesheet），class 承载 box-shadow/尺寸/光标态。
- 既有 `BaseWorkflowNode.test.ts` 增 `global.plugins:[i18n]`（组件现依赖 `useI18n`，无 i18n 实例会抛），为测试基础设施适配，原有断言逐字不变（零回归）。

## Deviations from Plan

None - plan executed exactly as written.

（说明：为兼容组件新增的 `useI18n` 依赖，给既有 `BaseWorkflowNode.test.ts` 补 i18n plugin 属测试基础设施适配，非生产行为变更。新建/修改的 composable 导入路径为 `../composables/`，因 `useNodeStyle` 在 `nodes/composables/` 而新 composable 在 `editor/composables/`，构建解析后 eslint --fix 自动归位导入顺序。）

## Issues Encountered
- 初次将新 composable 写成 `./composables/useConnectionDragState`，但 `useNodeStyle` 在 `nodes/composables/`、新 composable 在上一级 `editor/composables/` → vite 解析失败；改为 `../composables/...`。
- 单测最初按 rgb 断言 handle 着色，实际 inline style 保留 hex 原文（`#f59e0b`/`#10b981`/`#ef4444`）→ 改断言 hex。
- 既有 `BaseWorkflowNode.test.ts` 因组件新增 `useI18n()` 而需 i18n 实例 → 补 `createI18n` + `global.plugins`。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 节点卡层面插槽视觉全部就位：端口方形/圆形 + shape 着色 + 拖拽兼容/禁止态 + IM 门控锁徽标 + 附着徽标，既有节点渲染零回归。
- 93-06 可在此基础上接画布级磁吸交互（`@connect-start`/`@connect-end` 驱 `startConnect`/`endConnect` + `CustomConnectionLine` 消费 `findSnapTarget` 吸附端点 + 不兼容 Toast 消费 `incompatibleBody` + 拖拽 attach/detach 调 93-03 store 入口）+ 人工验收。

## Self-Check: PASSED

- FOUND: web/src/components/workflow/editor/composables/useImCapability.ts
- FOUND: web/src/components/workflow/editor/composables/__tests__/useImCapability.test.ts
- FOUND: web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.slot.test.ts
- FOUND: commit 2be8f2b13 (Task 1)
- FOUND: commit 849959d31 (Task 2)
- vitest BaseWorkflowNode(13) + useImCapability(6) + workflow 全组 106 全绿、vue-tsc --noEmit 通过、受改文件 eslint 干净。

---
*Phase: 93-capability-slot-editor*
*Completed: 2026-06-27*
