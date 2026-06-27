---
phase: 93-capability-slot-editor
plan: 02
subsystem: ui
tags: [vue, vue-flow, workflow-editor, port-shape, slot, snap, composable]

# Dependency graph
requires:
  - phase: 93-capability-slot-editor
    provides: "portShapes.ts（arePortShapesCompatible 空通配 + resolvePortShape store O(1) 解析）— 93-01 契约判定地基"
provides:
  - "useConnectionDragState.ts：模块级单例拖拽连接态 holder（dragging + 源 handle/shape）+ isCompatibleTarget（compatible-highlight 数据源），跨 BaseWorkflowNode/WorkflowCanvas 共享"
  - "usePortSnap.ts：PORT_SNAP_THRESHOLD=28（独立于 SNAP_THRESHOLD=5）+ findSnapTarget 纯几何（仅吸附兼容候选 + zoom 换算 + 取半径内最近）"
affects: [93-05, 93-06, capability-slot-editor, 磁吸, snap-locked, compatible-highlight]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "模块级单例响应式 holder 跨 UI 组件共享拖拽态（对齐既有 alignment overlay 单例思路），避免两 Wave 3 UI plan 互改文件"
    - "端口吸附与节点对齐双套独立阈值（PORT_SNAP_THRESHOLD=28 vs SNAP_THRESHOLD=5），磁吸新逻辑零污染既有对齐"
    - "吸附几何为纯函数（不查 store / 不建每帧对象），兼容性由调用方预标注，安全用于高频拖拽 + 可单测"

key-files:
  created:
    - web/src/components/workflow/editor/composables/useConnectionDragState.ts
    - web/src/components/workflow/editor/composables/usePortSnap.ts
    - web/src/components/workflow/editor/composables/__tests__/useConnectionDragState.test.ts
    - web/src/components/workflow/editor/composables/__tests__/usePortSnap.test.ts
  modified: []

key-decisions:
  - "useConnectionDragState 暴露 readonly(dragging)/readonly(source) 防消费者直改单例；startConnect/endConnect 为唯一写入口"
  - "usePortSnap 阈值换算用 PORT_SNAP_THRESHOLD/zoom（屏幕 28px ⇒ flow 距离随缩放变化），非法 zoom（≤0/非有限）回退 1 杜绝除零/NaN"
  - "findSnapTarget 不查 store、candidate.compatible 由调用方（93-06）用 isCompatibleTarget 预标注，保持纯几何可单测"

patterns-established:
  - "拖拽态 + 吸附几何拆为两个纯逻辑 composable，使 Wave 3 两个 UI plan（93-05 handle 类 / 93-06 画布交互）可并行消费而不互改文件"
  - "吸附只改拖拽连接线视觉端点，落点仍经 isValidConnection + getValidationError 双校验（吸附不绕合法性）"

requirements-completed: [SLOT-03]

# Metrics
duration: ~5min
completed: 2026-06-27
---

# Phase 93 Plan 02: 磁吸共享逻辑（useConnectionDragState + usePortSnap）Summary

**SLOT-03 磁吸抽出两个纯逻辑 composable：模块级单例拖拽连接态 holder（源 shape + 兼容判定，compatible-highlight 数据源）+ 端口吸附几何（PORT_SNAP_THRESHOLD=28 独立阈值、按 viewport.zoom 换算、仅吸附形状兼容候选），吸附只改视觉端点不绕合法性，节点对齐 SNAP_THRESHOLD=5 零回归。**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-27T12:59:45Z
- **Completed:** 2026-06-27T13:04:37Z
- **Tasks:** 2
- **Files modified:** 4（created 4 + modified 0）

## Accomplishments
- 新建 `useConnectionDragState.ts`：模块级单例响应式拖拽态（`dragging` + `source{nodeId,handleId,shape}`，composable 外定义跨组件共享），导出 `startConnect`/`endConnect`/只读 `dragging`/`source` + `isCompatibleTarget(targetNodeType, targetHandleId)`（复用 `arePortShapesCompatible(source.shape, resolvePortShape(.., 'input'))`，空契约通配，未拖拽/无源恒 false）。供 93-05（BaseWorkflowNode handle 类）与 93-06（WorkflowCanvas connect-start/end）共享，避免互改文件。
- 新建 `usePortSnap.ts`：独立常量 `PORT_SNAP_THRESHOLD = 28`（与 "+" 热区 `-7`=28px 对齐，**绝不**改 `useAlignmentGuides.SNAP_THRESHOLD=5`）+ 纯函数 `findSnapTarget(pointer, candidates, zoom)`：仅在 `compatible===true` 候选中比距、屏幕阈值换算到 flow（`28/zoom`）、取半径内欧氏最近者返回 handle 中心端点，无命中返回 null；非法 zoom 防御回退 1。
- 单测覆盖：拖拽态切换、兼容/不兼容/空通配判定、未拖拽/endConnect 后恒 false、单例联动；吸附命中/最近/不兼容跳过/超距不命中/边界命中/zoom 0.5 与 2 换算/非法 zoom 防御 + `SNAP_THRESHOLD=5` 源码守护断言（节点对齐零回归）。

## Task Commits

Each task was committed atomically:

1. **Task 1: useConnectionDragState 拖拽连接态 holder** - `cfbad4e6d` (feat)
2. **Task 2: usePortSnap 端口吸附几何（28px 独立阈值）** - `9327ee51c` (feat)

**Plan metadata:** (final docs commit — see below)

## Files Created/Modified
- `web/src/components/workflow/editor/composables/useConnectionDragState.ts` - 模块级单例拖拽连接态 holder + 契约兼容判定（compatible-highlight 数据源）
- `web/src/components/workflow/editor/composables/usePortSnap.ts` - 端口吸附几何（PORT_SNAP_THRESHOLD=28 独立常量 + findSnapTarget 纯几何 + zoom 换算）
- `web/src/components/workflow/editor/composables/__tests__/useConnectionDragState.test.ts` - 拖拽态切换/兼容判定/空通配/单例联动单测（7 例）
- `web/src/components/workflow/editor/composables/__tests__/usePortSnap.test.ts` - 命中/跳过/最近/zoom 换算/非法 zoom + SNAP_THRESHOLD 零回归守护单测（11 例）

## Decisions Made
- `useConnectionDragState` 返回 `readonly(dragging)` / `readonly(source)`，防消费组件直改单例状态；写入仅经 `startConnect`/`endConnect` 两入口。
- `usePortSnap` 阈值换算取 `PORT_SNAP_THRESHOLD / zoom`（屏幕像素恒定、flow 距离随缩放变化，保证不同缩放手感一致）；`zoom` 非有限或 ≤0 时回退为 1（按屏幕阈值比），杜绝除零/NaN。
- `findSnapTarget` 保持纯几何：不查 store、不感知拖拽态，candidate 的 `compatible` 由调用方（93-06）用 `useConnectionDragState.isCompatibleTarget` 预标注后传入——契合"高频拖拽路径纯函数、可单测"的 UI-SPEC 约束。

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- usePortSnap 守护测试初版用 `fileURLToPath(new URL(..., import.meta.url))` 读 `useAlignmentGuides.ts` 源码，在该 vitest 环境下 `import.meta.url` 非 `file://` scheme 报 `TypeError: The URL must be of scheme file` → 改为 `resolve(process.cwd(), 'src/.../useAlignmentGuides.ts')`（vitest cwd=web/）。
- eslint：`import { ..., type SnapCandidate }` 内联 type 说明符触发 `import/consistent-type-specifier-style`、`describe` 标题首字符大写触发 `test/prefer-lowercase-title`、type 导入排序触发 `perfectionist/sort-imports` → 拆出顶层 `import type`、describe 标题改以中文起头、`eslint --fix` 修正导入顺序（并把文件头 docstring 复位至顶部）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 磁吸共享逻辑就位：`useConnectionDragState`（拖拽态 + 兼容判定）+ `usePortSnap`（28px 独立阈值 + zoom 换算 + 仅兼容吸附）。
- 下游 Wave 3 可并行消费：93-05（BaseWorkflowNode handle 绑定 compatible-highlight/forbidden 态，读 `dragging`/`isCompatibleTarget`）、93-06（WorkflowCanvas `@connect-start`/`@connect-end` 驱动 `startConnect`/`endConnect` + CustomConnectionLine 消费 `findSnapTarget` 吸附端点）。
- 合法性边界明确：吸附仅改视觉端点，落点仍由 `isValidConnection` + `getValidationError`（93-01）双校验，磁吸不放行非法连接（T-93-02-BYPASS 已缓解）。
- 节点对齐 `SNAP_THRESHOLD=5` 零回归（源码守护断言锁定），端口吸附为独立常量不污染既有对齐逻辑。

## Self-Check: PASSED

- FOUND: web/src/components/workflow/editor/composables/useConnectionDragState.ts
- FOUND: web/src/components/workflow/editor/composables/usePortSnap.ts
- FOUND: web/src/components/workflow/editor/composables/__tests__/useConnectionDragState.test.ts
- FOUND: web/src/components/workflow/editor/composables/__tests__/usePortSnap.test.ts
- FOUND: commit cfbad4e6d (Task 1)
- FOUND: commit 9327ee51c (Task 2)

---
*Phase: 93-capability-slot-editor*
*Completed: 2026-06-27*
