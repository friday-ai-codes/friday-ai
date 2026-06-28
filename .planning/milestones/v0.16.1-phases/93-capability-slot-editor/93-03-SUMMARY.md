---
phase: 93-capability-slot-editor
plan: 03
subsystem: ui
tags: [vue-flow, pinia, workflow-editor, dagre, parent-child, slot-04]

# Dependency graph
requires:
  - phase: 90-clarification-capability
    provides: 澄清节点能力与节点元数据透传约定
provides:
  - store attachChild/detachChild/getChildNodes（经 metadata.parentNodeId 持久化，零后端 schema 变更）
  - removeNode 级联删除附着子节点 + 两者相关边（生命周期绑定）
  - toVueFlowNodes parentNode + extent:'parent' 映射 + 父先子排序
  - 数据契约：top-level parentNode 与 data.metadata.parentNodeId 同源并存（93-05 徽标读取来源）
  - useAutoLayout 把附着子节点排除出 dagre，父子作为整体随父定位
affects: [93-05, 93-06, capability-slot-editor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "父子关系经既有 metadata JSON 列（metadata.parentNodeId）持久化，零后端字段/迁移"
    - "Vue Flow parentNode + extent:'parent' 编组 + 父先子两趟稳定排序"
    - "数据契约同源：顶层 parentNode 与 data.metadata.parentNodeId 双写不丢，固化跨 plan 读取来源"

key-files:
  created:
    - web/src/stores/__tests__/useWorkflowsStore.attach.test.ts
    - web/src/components/workflow/editor/composables/__tests__/useWorkflowTransform.parent.test.ts
  modified:
    - web/src/stores/useWorkflowsStore.ts
    - web/src/components/workflow/editor/composables/useWorkflowTransform.ts
    - web/src/components/workflow/editor/composables/useAutoLayout.ts

key-decisions:
  - "用 metadata.parentNodeId 持久化父子关系（Claude's Discretion）：metadata 是既有可持久 JSON 列，经 bulk-update 透传，无新后端字段/迁移，无新权限面"
  - "detachChild 用对象解构剔除 parentNodeId 键（非置 null），保证往返不残留脏键"
  - "父先子排序用两趟过滤（先无 parent 再有 parent）而非比较器，稳定且 O(n)"

patterns-established:
  - "父子持久化：metadata.parentNodeId 单一入口（attach/detach），removeNode 反查级联"
  - "数据契约断言：单测同时校验 node.parentNode 与 node.data.metadata.parentNodeId 同源"

requirements-completed: [SLOT-04]

# Metrics
duration: 11min
completed: 2026-06-27
---

# Phase 93 Plan 03: 附着子节点数据模型与生命周期绑定 Summary

**用 `metadata.parentNodeId` 持久化澄清节点对方案节点的附着关系（零后端 schema 变更），映射为 Vue Flow `parentNode + extent:'parent'`、删父级联删子、autoLayout 把父子视为整体。**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-27T12:23:00Z
- **Completed:** 2026-06-27T12:34:00Z
- **Tasks:** 2
- **Files modified:** 5（3 改 + 2 新增测试）

## Accomplishments
- store 新增 `attachChild`/`detachChild`/`getChildNodes` 单一入口，经 `metadata.parentNodeId` 持久化父子关系，attach/detach 各入历史一次（单步可撤销）。
- `removeNode` 兑现生命周期绑定：删父方案节点时反查 `metadata.parentNodeId===nodeId` 级联删除全部附着子节点及两者相关边；普通节点删除零回归。
- `toVueFlowNodes` 把附着子节点映射为 `parentNode + extent:'parent'`，并以两趟稳定排序保证父节点恒先于子节点（规避 Vue Flow "parent node not found"）。
- **数据契约固化（WARNING 1 跨 plan）**：顶层 `parentNode` 与 `data.metadata.parentNodeId` 同源并存，单测断言两者相等，锁死 93-05 经 `props.data.metadata.parentNodeId` 判附着徽标的唯一权威来源。
- `useAutoLayout` 把附着子节点排除出 dagre 输入与坐标写回，父子作为整体随父定位，无父子图零回归。

## Task Commits

Each task was committed atomically:

1. **Task 1: store parentNodeId 持久化 + attach/detach + 级联删除** - `79c00c5e4` (feat)
2. **Task 2: transform parentNode/extent 映射 + 父先子排序 + autoLayout 编组整体** - `e833879d1` (feat)

_无 TDD 拆分，每个 task 含实现 + 单测一次提交。_

## Files Created/Modified
- `web/src/stores/useWorkflowsStore.ts` - 新增 attachChild/detachChild/getChildNodes，removeNode 级联删除子节点 + 连边。
- `web/src/components/workflow/editor/composables/useWorkflowTransform.ts` - toVueFlowNodes 父子映射 + 同源数据契约 + 父先子排序。
- `web/src/components/workflow/editor/composables/useAutoLayout.ts` - applyAutoLayout 排除附着子节点出 dagre。
- `web/src/stores/__tests__/useWorkflowsStore.attach.test.ts` - attach/detach/级联/往返持久化/普通节点零回归单测（7 例）。
- `web/src/components/workflow/editor/composables/__tests__/useWorkflowTransform.parent.test.ts` - 映射/同源契约/排序/往返/无父子零回归/autoLayout 不动子节点单测（7 例）。

## Decisions Made
- **metadata.parentNodeId 持久化（Claude's Discretion）**：父子关系仅是编辑器视觉/生命周期元数据，落既有 `metadata` JSON 列，后端 bulk-update 既有校验不变，零新字段/迁移/权限面（对齐 threat register T-93-03-DATA: accept）。
- **detachChild 删键而非置 null**：用对象解构 `const { parentNodeId: _drop, ...rest } = metadata` 重建 metadata，保证 save/reload 往返无脏键残留。
- **父先子排序两趟过滤**：先输出无 parent 节点再输出有 parent 节点，O(n) 且稳定，避免比较器复杂度与不稳定性。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- 单测最初对 setup-store 的 `nodes`/`edges`/`currentWorkflow` 直接重新赋值，因 store 返回值带 `as const` 致 TS 报 readonly（TS2540）。改为 `arr.push(...)` 原地变更（beforeEach 已 fresh pinia 故数组为空），`currentWorkflow` 用窄类型断言赋值。vue-tsc 与 vitest 均转绿。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 93-05 可经 `props.data.metadata.parentNodeId` 读取附着徽标（数据契约已固化并被单测锁定）。
- 93-06 可调用 store `attachChild(childId, parentId, relativePosition)` / `detachChild(childId, absolutePosition)` 完成拖拽附着/解除（相对/绝对坐标换算由调用方负责）。
- 父子持久化、级联删除、transform 同源映射、autoLayout 整体处理均就绪，无父子图零回归。

## Self-Check: PASSED

- 全部 5 个源/测试文件 + SUMMARY.md 落盘存在。
- Task 1 `79c00c5e4` / Task 2 `e833879d1` 提交均存在。
- vitest（14 例）全绿、vue-tsc --noEmit 通过、eslint 清洁。

---
*Phase: 93-capability-slot-editor*
*Completed: 2026-06-27*
