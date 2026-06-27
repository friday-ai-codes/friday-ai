---
phase: 93-capability-slot-editor
plan: 01
subsystem: ui
tags: [vue, vue-flow, workflow-editor, port-shape, slot, i18n, connection-validation]

# Dependency graph
requires:
  - phase: 93-capability-slot-editor
    provides: "NodePortSerializer.shape 字段 — GET /api/node-types/ 端到端向前端真实回传端口 shape（93-00）"
  - phase: 92-capability-slot-backend
    provides: "NodePort.shape 语义 + WorkflowGraphValidator._validate_port_shapes 后端兜底校验（空契约=通配同口径）"
provides:
  - "useNodeTypesStore.NodePort.shape?:string 类型字段（前端消费 /node-types/ 真实回传 shape）"
  - "portShapes.ts：arePortShapesCompatible（空通配纯函数）+ resolvePortShape（store O(1) 解析）+ SHAPE_DISPLAY_KEY/shapeDisplayName（shape→中文友好名）"
  - "useConnectionValidator 第 4 条契约兼容规则（前端权威即时判定，不兼容拒连）"
  - "workflow.editor.{slot,shape,palette}.* 全量中文 i18n 键（覆盖 UI-SPEC Copywriting Contract，本 phase 一次性落 locale）"
affects: [93-02, 93-05, 93-06, capability-slot-editor, 磁吸, 端口着色, 附着徽标, IM门控]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "前端权威即时判定 + 后端兜底：连接合法性前端纯函数判定，后端 _validate_port_shapes 保存时仍是最终防线"
    - "空契约=通配为零回归命门：任一端 shape 空（含 default/error 通用端口）即放行，与后端同口径"
    - "i18n 守护范式（Phase 24/91）：真实 zh-CN.json 作 createI18n messages 锁关键中文文案不被改空"

key-files:
  created:
    - web/src/components/workflow/editor/composables/portShapes.ts
    - web/src/components/workflow/editor/composables/__tests__/portShapes.test.ts
    - web/src/components/workflow/editor/composables/__tests__/useConnectionValidator.test.ts
  modified:
    - web/src/stores/useNodeTypesStore.ts
    - web/src/components/workflow/editor/composables/useConnectionValidator.ts
    - web/src/components/workflow/editor/WorkflowCanvas.vue
    - web/src/locales/zh-CN.json

key-decisions:
  - "getValidationError 新增可选 t 注入参数（Translator），WorkflowCanvas onConnect 经 useI18n t 传入；validateConnection（boolean 路径）不传 t，无 t 时回退内置中文模板仅用于 boolean 非法判定（不展示给用户），保持 isValidConnection 签名不变"
  - "resolvePortShape 经 useNodeTypesStore().getNodeType（既有 O(1) find），未就绪/未知端口返回 undefined 不抛，高频拖拽路径纯函数不打日志"
  - "shapeDisplayName 无 t 或无映射时回退原 shape，空 shape → 空串；UI Toast 路径恒传 t 故展示中文友好名，不暴露英文标识符"

patterns-established:
  - "shape 兼容纯函数与后端 _validate_port_shapes 严格同口径（空通配 + 双非空相等），前后端判定一致"

requirements-completed: [SLOT-03]

# Metrics
duration: ~9min
completed: 2026-06-27
---

# Phase 93 Plan 01: 契约判定地基（portShapes + useConnectionValidator 第 4 条 + i18n）Summary

**前端从 `/api/node-types/` 读取端口 shape 并在连接校验链追加「形状契约兼容」第 4 条（前端权威即时判定、后端兜底），不兼容 typed 连接被判非法且 Toast 展示中文 shape 友好名；空契约通配零回归；workflow.editor.* 全量中文 i18n 键一次性落地。**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-27T12:45:35Z
- **Completed:** 2026-06-27T12:54:30Z
- **Tasks:** 2
- **Files modified:** 7（created 3 + modified 4）

## Accomplishments
- `useNodeTypesStore.NodePort` 追加可选 `shape?: string`，前端消费 93-00 经 `/node-types/` 真实回传的端口契约 shape。
- 新建 `portShapes.ts`：`arePortShapesCompatible`（空通配 + 双非空相等，与后端 `_validate_port_shapes` 同口径）、`resolvePortShape`（按 node_type+handle 从 store O(1) 取 shape，未就绪/未知端口返回 undefined 不抛）、`SHAPE_DISPLAY_KEY` + `shapeDisplayName`（7 个 typed shape → 中文友好名，不暴露英文标识符）。
- `useConnectionValidator.getValidationError` 在既有「防自连 / 四元组重复 / BFS 防环」三规则后追加第 4 条「契约形状兼容」：解析两端 nodeType+handle 取 shape，不兼容时返回含中文 shape 名的 `incompatibleBody`；缺类型/缺 shape/空契约一律不拦截（零回归）。
- `WorkflowCanvas.onConnect` 经 `useI18n` 注入 `t`，Toast 标题/正文走 i18n 键。
- `zh-CN.json` 新增 `workflow.editor.slot.*` / `shape.*` / `palette.empty` 全量键（覆盖 UI-SPEC Copywriting Contract，本 phase 独占写 locale，后续 Wave 只读）。
- 守护单测：真实 `zh-CN.json` 锁「形状不兼容/澄清请求/附着」等中文不被改空；既有三规则（自连/重复/环）补回归断言逐字不变。

## Task Commits

Each task was committed atomically:

1. **Task 1: NodePort.shape 字段 + portShapes 契约兼容纯逻辑** - `739cce043` (feat)
2. **Task 2: useConnectionValidator 契约兼容第 4 条 + workflow i18n 全量键** - `8bc8efd02` (feat)

**Plan metadata:** (final docs commit — see below)

## Files Created/Modified
- `web/src/components/workflow/editor/composables/portShapes.ts` - shape 兼容纯函数 + store shape 解析 + shape→中文名映射（SLOT-03 前端判定核心）
- `web/src/components/workflow/editor/composables/__tests__/portShapes.test.ts` - 纯函数四态（空通配/相等/不等/缺失）+ resolvePortShape store 解析单测
- `web/src/components/workflow/editor/composables/__tests__/useConnectionValidator.test.ts` - 第 4 条契约兼容 + 既有三规则零回归 + 真实 zh-CN.json i18n 守护
- `web/src/stores/useNodeTypesStore.ts` - `NodePort` 追加可选 `shape?: string`
- `web/src/components/workflow/editor/composables/useConnectionValidator.ts` - `getValidationError` 第 4 条契约兼容规则 + 可选 `t` 注入参数
- `web/src/components/workflow/editor/WorkflowCanvas.vue` - onConnect 经 `useI18n` 传入 `t`，Toast 标题/正文走 i18n
- `web/src/locales/zh-CN.json` - 新增 `workflow.editor.slot/shape/palette` 全量中文键

## Decisions Made
- `getValidationError(connection, t?)` 可选 `t` 注入：UI Toast 路径（onConnect）传 `t` 渲染中文 shape 名；`validateConnection`（`:is-valid-connection` boolean 路径）不传 `t`，不兼容时回退内置中文模板（仅用于 boolean 非法判定、不展示给用户），`validateConnection` 签名保持不变。
- `resolvePortShape` 复用 `useNodeTypesStore().getNodeType`（既有 O(1) find），store 未就绪/未知节点类型/未知端口均返回 `undefined` 不抛；纯函数不打日志，安全用于高频拖拽 `isValidConnection`。
- `shapeDisplayName` 无映射/无 `t` 回退原 shape、空 shape → 空串；UI 路径恒有 `t` 与映射故展示中文友好名，不向用户暴露 `clarification_request` 等英文标识符（满足 T-93-01-INFO）。

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- 单测对 `i18n.global.t` 取值触发 `vue-tsc` TS2589（类型实例化过深）→ 改为 `(i18n.global as any).t` 断言为简单 Translator 函数签名（不影响运行时）。
- eslint `test/prefer-lowercase-title` 要求测试标题首字符小写 → 调整以大写英文（`SHAPE_DISPLAY_KEY`/`BFS`）开头的 `it` 标题措辞。
- `web/src/locales/zh-CN.json` 在本 plan 开始前已有一处无关 war-room 未提交改动（`chat.*.close: "关闭"`）；用 `git add -p` 仅暂存本 plan 的 `workflow` namespace hunk，未提交该无关行（保持工作树原状）。

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 契约判定地基就位：`portShapes` 兼容纯函数 + `resolvePortShape` + shape 中文名 + `useConnectionValidator` 第 4 条 + 全量 i18n 键。
- 下游可推进：93-02（磁吸 useConnectionDragState/usePortSnap 消费 `arePortShapesCompatible`）、93-05（端口着色 + 附着徽标，消费 `SHAPE_DISPLAY_KEY` 与 shape 字段）、93-06（画布磁吸交互 + 不兼容 Toast 消费 `incompatibleBody`）。
- i18n 键空间 `workflow.editor.*` 已全量落地，后续 Wave plan 只消费不再改 `zh-CN.json`。

## Self-Check: PASSED

- FOUND: web/src/components/workflow/editor/composables/portShapes.ts
- FOUND: web/src/components/workflow/editor/composables/__tests__/portShapes.test.ts
- FOUND: web/src/components/workflow/editor/composables/__tests__/useConnectionValidator.test.ts
- FOUND: commit 739cce043 (Task 1)
- FOUND: commit 8bc8efd02 (Task 2)

---
*Phase: 93-capability-slot-editor*
*Completed: 2026-06-27*
