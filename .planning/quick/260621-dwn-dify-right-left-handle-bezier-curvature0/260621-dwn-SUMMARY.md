---
quick_id: 260621-dwn
phase: quick-260621-dwn
plan: 01
type: execute
status: complete
completed_date: 2026-06-21
---

# Quick 260621-dwn：画布对标 dify 横向 Handle 与单一 bezier 连线 Summary

把 friday-ai 工作流画布（Vue Flow）对标 dify 重做：消灭"连线飘"病根（Handle 与边方向自相矛盾），统一横向 L→R 布局 + 单一 curvature 0.16 bezier 边，并补齐一键自动布局、边中点插入节点、Handle 旁加节点、四元组重复边校验。

## 提交记录（仅 web/，未触碰 server/）

| Task | Commit | 说明 |
| ---- | ------ | ---- |
| Task 1 (P0) | `e5ddd5c5e` | 横向 Handle（左入右出）+ 单一 0.16 bezier 边 + 拖拽连线一致 |
| Task 2 (P1) | `87ce25eba` | 一键横向自动布局 + 边中点 "+" 插入节点 |
| Task 3 (P2-P3) | `f3cf6f50b` | 边四元组类型/校验 + Handle 旁加节点 + 分支出边稳定排序 |

每次提交均用 `git commit -- <逐个 web/ 文件路径>` 路径限定提交，绕开工作区中**与本任务无关的 server/ 未提交改动**（提交时确认 0 个 server/ 文件进入提交）。

## 实际改动文件清单

### Task 1（commit e5ddd5c5e，8 文件）
- `web/src/components/workflow/editor/utils/edgeRouting.ts` — 删除三分支自适应逻辑，收敛为单一 `getBezierPath({ sourceX-8, Right, targetX+8, Left, curvature 0.16 })`；移除 `EdgeRouteResult.strategy` 与 `getSmoothStepPath` 导入。
- `web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue` — 入 Handle `Position.Left`、出 Handle `Position.Right`；`portLeft`→`portTop`（垂直均分）；触发器（inputPorts 为空）不渲染入 Handle。
- `web/src/components/workflow/editor/nodes/DynamicPortNode.vue` — 动态 Handle 改 `parallel?Right:Left`；`portLeft`→`portTop`。
- `web/src/components/workflow/editor/nodes/DefaultWorkflowNode.vue` — **[Rule 1 偏离]** 该组件未在 nodeTypes 注册（注册表 fallback 用 BaseWorkflowNode），但仍残留 Top/Bottom Handle，按"不得遗留 Top/Bottom"病根修复一并改为 Left/Right。
- `web/src/components/workflow/editor/edges/GradientEdge.vue` — strokeWidth 固定 2（选中 2.5），保留 gradient/发光/虚线动画，路径取单一 bezier。
- `web/src/components/workflow/editor/edges/CustomConnectionLine.vue` — **新建**，拖拽连线组件（`ConnectionLineProps`，同参数 bezier）。
- `web/src/components/workflow/editor/WorkflowCanvas.vue` — `#connection-line` 具名插槽接入 `CustomConnectionLine`。
- `web/src/components/__tests__/workflow-edge-routing.test.ts` — **[Rule 3 偏离]** 原测试断言已删除的 `strategy` 字段导致 type-check 失败，改写为单一 bezier 行为断言（`path` 含 `C`、labelX/labelY 为数值）。

> 备注：`web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts` 的目标改动（Handle position 断言 + 触发器无入 Handle 用例 + mock 暴露 `data-handle-position`）在当前 HEAD 中已是同样内容（git 无 diff），未进入本次提交；该 5 个用例已存在且 `vitest` 全绿。

### Task 2（commit 87ce25eba，9 文件）
- `web/src/components/workflow/editor/composables/useAutoLayout.ts` — **新建**，dagre `rankdir:'LR'` 计算坐标，逐节点 `updateNodePosition` + 末尾 `saveToHistory()` 一次（单步可撤销），空图返回 false。
- `web/src/components/workflow/workflowFocus.ts` — `WorkflowFocusContext` 增加 `autoLayout: (() => void) | null`。
- `web/src/components/workflow/editor/WorkflowCanvas.vue` — `runAutoLayout()`（applyAutoLayout + fitView），挂载写入 `workflowFocus.autoLayout`，卸载置 null。
- `web/src/components/workflow/WorkflowToolbar.vue` — 撤销/重做旁新增「自动整理布局」按钮（`Network` 图标 + Tooltip），emits `autoLayout`。
- `web/src/pages/workflows/[id].vue` — `autoLayout: null` 初始化持有器；`@auto-layout="onAutoLayout"` → `workflowFocus.autoLayout?.()`。
- `web/src/components/workflow/editor/NodeInsertMenu.vue` — **新建**，可复用节点选择 popover（reka-ui Popover；按分类分组 + 搜索；`emit('select', nodeType)`）。
- `web/src/components/workflow/editor/edges/GradientEdge.vue` — `EdgeLabelRenderer` 中点悬停 "+"（透明加宽命中路径驱动 hover）；`onInsert` 删旧边 + 加节点 + 两条新边。
- `web/src/components/workflow/editor/composables/useDragAndDrop.ts` — 移除 `pointToLineDistance`/`EDGE_HIT_TOLERANCE`/hitEdge 分支，`onDrop` 始终只 `addNode` + recordRecentNode。
- `web/src/components/workflow/editor/composables/__tests__/useDragAndDrop.test.ts` — 移除点线命中相关用例，新增「有 edge 也只 addNode」断言；保留 onDragOver/recent 副作用/getRecentNodes（9 用例全绿）。

### Task 3（commit f3cf6f50b，5 文件）
- `web/src/components/workflow/editor/composables/useWorkflowTransform.ts` — `toVueFlowEdges(storeEdges, storeNodes?)` 派生 `data.sourceType/targetType`（不入 store）；`WorkflowEdgeData` 加两字段。
- `web/src/components/workflow/editor/composables/useConnectionValidator.ts` — 重复边判定改 source/sourceHandle/target/targetHandle 四元组（`?? 'default'` 归一），修复不同分支端口误报；防自连/防环不变。
- `web/src/components/workflow/editor/WorkflowCanvas.vue` — `toVueFlowEdges(storeEdges.value, storeNodes.value)`。
- `web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue` — hover 出/入 Handle 旁浮出 "+"（group-hover），`appendNode(direction, nodeType)` 追加并自动连线；触发器无入向 "+"；DynamicPortNode 管理的方向（hideHandles）不显示对应 "+"。
- `web/src/components/workflow/editor/composables/useAutoLayout.ts` — 新增纯函数 `sortBranchEdges`（同源出边按 handle 名排序、else/false/default 殿后），布局前对 dagre 输入边排序。

## P3 端口 ID 对齐后端 — 决策：延后（DEFERRED）

**不做**。决策依据（plan 决策原则「成本高就干净延后，不留半成品」）：
- DynamicPortNode 现用 `port-1`/`port-${Date.now()}`，对齐后端需改默认端口与 addPort 命名为 `branch_0/branch_1...`（parallel）、`input_0/input_1...`（join），并把端口增删从 `useVueFlow().updateNodeData` 改为 `store.updateNode` 回写 Pinia。
- 该改动触及**后端端口 ID 契约**（parallel/condition 分支命名）与**存量工作流迁移面**（已保存的 edge `sourcePort='port-1'` 句柄会失配，需迁移），属中-高成本/高风险，且与本 quick 核心「连线交互对标 dify」相关性较低。
- 为避免引入半成品不一致状态，本任务保持现状，留作后续独立任务处理。

## 验证结果

| 命令（在 web/ 下） | 结果 |
| ------------------ | ---- |
| `pnpm vitest run src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts` | ✅ 5 passed |
| `pnpm vitest run src/components/workflow/editor/composables/__tests__/useDragAndDrop.test.ts` | ✅ 9 passed |
| `pnpm vitest run src/components/workflow/editor` | ✅ 3 files / 25 passed |
| `pnpm vitest run src/components/__tests__/workflow-edge-routing.test.ts` | ✅ 3 passed |
| `pnpm type-check`（vue-tsc --noEmit） | ✅ 通过 |
| `pnpm lint`（@antfu eslint，对改动文件，CI 模式） | ✅ 0 error |
| grep：edgeRouting/GradientEdge/CustomConnectionLine 无 `Position.Top/Bottom` | ✅ NONE |
| grep：Base/DynamicPortNode Handle position 仅 Left/Right | ✅（BaseWorkflowNode 的 `Position.Top` 仅 NodeToolbar 工具栏定位，非 Handle） |

> 说明：`pnpm lint` / `pnpm type-check` 全项目命令已跑（type-check 全绿）；lint 因工作区存在并发的其他任务改动，按范围对本任务改动文件单独验证 0 error。

## Deviations from Plan

- **[Rule 3 - 阻断修复]** `src/components/__tests__/workflow-edge-routing.test.ts`：删除 `EdgeRouteResult.strategy` 后该既有测试 type-check 报错，改写为单一 bezier 断言。
- **[Rule 1 - 一致性]** `DefaultWorkflowNode.vue`：未注册的临时节点组件残留 Top/Bottom Handle，按病根修复目标一并改为 Left/Right（低风险，组件当前不参与渲染路径）。

## 验收反馈修复轮（commit `42fcdffd6`）

人工验收时提出的 7 个问题，处理如下：

| # | 问题 | 性质 | 处理 |
| - | ---- | ---- | ---- |
| 1 | 还允许拖拽进来吗 | 正常 | 保留侧栏拖拽（`onDrop` 仍生效），与 "+" 并存，比 dify 更灵活 |
| 2 | "+" 与连线看着挤 | 体验 | 拉开间距（见 C），短边不再拥挤 |
| 3 | 点 "+" 弹出节点配置 | 误触 | "+" 按钮 `@click/mousedown/pointerdown.stop` 阻止冒泡，避免近距误点节点触发选中/配置；`addNode` 本就不 selectNode |
| 4 | 虚线常驻 | **真 bug** | 对齐参考线改为仅拖拽时渲染（`isDragging` + `node-drag-start/stop`），松手即清 |
| 5 | 右上角黄点 | 正常 | 是"配置已修改未保存"指示器（`isDirty`），非 dify 概念，保留 |
| 6 | dify 的成功/失败双出口 | 增强→**延后** | 后端 `on_error` 是 abort/retry/ignore **策略**，无"失败分支句柄"路由语义；UI 加 error 出口会造后端无法路由的边，需后端先支持，延后 |
| 7 | 节点内容太少 | 增强 | 节点 body 回退显示配置摘要（描述/关键 config 字段），对标 dify（见 D）|

本轮代码改动（commit `42fcdffd6`，4 文件，仅 web/）：
- `WorkflowCanvas.vue` — 对齐参考线仅拖拽时显示（修复 #4 常驻虚线）。
- `NodeInsertMenu.vue` — "+" 触发器阻止事件冒泡 + 略放大（修复 #3 误触）。
- `composables/useAutoLayout.ts` — 间距对齐 dify：`ranksep 80→140 / nodesep 40→70`（修复 #2 拥挤）。
- `nodes/BaseWorkflowNode.vue` — 追加节点偏移 `280→340`；新增 `nodeSummary`（描述/config 关键字段），slot 回退渲染（增强 #7）；摘要字段表覆盖 模型/供应商/事件/条件/工具/语言/URL/提示词/知识库/仓库。

### E（成功/失败双出口）延后说明
后端 `server/workflows/engine/routing.py` 仅按 `source_handle` 选边，节点失败由 `on_error` 策略处理（abort 中止 / retry 重试 / ignore 容错继续），**不存在**"失败 → 走 error 句柄下游"的路由。要做 dify 式双出口，需后端先引入失败分支路由语义（新 handle + routing + 校验），属独立后端任务，本轮不动以免半成品。

验证（本轮）：`pnpm type-check` ✅；改动文件 `eslint` ✅ 0 error；`pnpm vitest run src/components/workflow/editor` ✅ 3 files / 25 passed。

## 待人工验收步骤（checkpoint:human-verify，blocking）

在 web/ 下 `pnpm dev`，打开任一工作流编辑页 `/workflows/{id}`：

1. **连线方向**：所有边从节点右侧出、左侧入，柔和 bezier，无折返/无"飘"。
2. **拖拽一致**：从某节点右侧 Handle 拖出连线，虚线预览与最终实线形状一致。
3. **触发器**：触发器节点（如 manual_trigger）左侧无入 Handle。
4. **自动布局**：点工具栏「自动整理布局」→ 节点横向 L→R 重排并居中；按撤销(Undo)一步还原。
5. **边中点插入**：悬停某条连线中点出现 "+"，点击选一个节点 → 原边断开、中间插入新节点并接好两条边。
6. **Handle 旁加节点**：悬停节点，右侧（出向）"+" 出现，点击选节点 → 右侧追加并自动连线；触发器节点左侧无入向 "+"。
7. **四元组校验**：从一个 parallel/condition 节点的**不同分支端口**连到同一目标，不再提示"已存在连接"。

回复"approved"或描述问题。
