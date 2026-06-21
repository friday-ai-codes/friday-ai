---
quick_id: 260621-dwn
phase: quick-260621-dwn
plan: 01
type: execute
wave: 1
depends_on: []
autonomous: false
requirements: [P0-1, P0-2, P1-3, P1-4, P2-5, P2-6, P3-7]
files_modified:
  - web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue
  - web/src/components/workflow/editor/nodes/DynamicPortNode.vue
  - web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts
  - web/src/components/workflow/editor/utils/edgeRouting.ts
  - web/src/components/workflow/editor/edges/GradientEdge.vue
  - web/src/components/workflow/editor/edges/CustomConnectionLine.vue
  - web/src/components/workflow/editor/WorkflowCanvas.vue
  - web/src/components/workflow/editor/composables/useWorkflowTransform.ts
  - web/src/components/workflow/editor/composables/useConnectionValidator.ts
  - web/src/components/workflow/editor/composables/useDragAndDrop.ts
  - web/src/components/workflow/editor/composables/__tests__/useDragAndDrop.test.ts
  - web/src/components/workflow/editor/composables/useAutoLayout.ts
  - web/src/components/workflow/editor/NodeInsertMenu.vue
  - web/src/components/workflow/workflowFocus.ts
  - web/src/components/workflow/WorkflowToolbar.vue
  - web/src/pages/workflows/[id].vue

must_haves:
  truths:
    - "节点入(target) Handle 永远在左边、出(source) Handle 永远在右边；多端口沿垂直方向均分"
    - "触发器节点（inputs 为空）不渲染入 Handle"
    - "所有连线为同一种 bezier（curvature 0.16，source=Right→target=Left），不再按相对位置切换 smooth-step/折返"
    - "拖拽中的连线（connectionLine）与连成后的边形状一致"
    - "点击工具栏'自动布局'按钮后所有节点按横向 L→R 重排、画布 fitView，且该操作可撤销"
    - "悬停连线时其中点浮出 '+' 按钮，点击选节点后在该边中间插入新节点（删旧边 + 新节点 + 两条新边）"
    - "同两节点不同分支端口的多条边不再被误判为重复连接"
  artifacts:
    - path: "web/src/components/workflow/editor/edges/CustomConnectionLine.vue"
      provides: "拖拽连线组件（与边同一 bezier 参数）"
    - path: "web/src/components/workflow/editor/composables/useAutoLayout.ts"
      provides: "横向 LR 自动布局 composable（写回 store + 历史 + fitView）"
    - path: "web/src/components/workflow/editor/NodeInsertMenu.vue"
      provides: "可复用节点选择 popover（边/Handle 加节点共用）"
  key_links:
    - from: "edgeRouting.ts"
      to: "GradientEdge.vue & CustomConnectionLine.vue"
      via: "单一 getBezierPath(Right/Left, curvature 0.16)"
    - from: "WorkflowToolbar 自动布局按钮"
      to: "WorkflowCanvas useAutoLayout + fitView"
      via: "workflowFocus 持有器（autoLayout）"
    - from: "GradientEdge '+' 按钮"
      to: "store.removeEdge/addNode/addEdge"
      via: "NodeInsertMenu 选择后插入"
---

<objective>
把 friday-ai 工作流画布（Vue Flow）对标 dify 重做：消灭"连线飘忽"病根，统一为横向 L→R 布局 + 单一 bezier 边，并补齐一键自动布局、边中点插入节点、Handle 内嵌加节点、四元组边校验等交互。

Purpose: 当前 Handle 渲染在 Top/Bottom，而 `edgeRouting.ts` 在横向时却按 Left/Right 弯，连线方向与 Handle 方向自相矛盾 → 连线飘。dify 的铁律是「Handle 永远 source=Right/target=Left，连线只有一种 curvature 0.16 的 bezier」，照抄即根治。

Output: 改造后的画布组件 + 连线组件 + 自动布局/插入交互；`pnpm -C web type-check`、`pnpm -C web lint`、相关 vitest 全绿。

dify 源码参考已 clone 到 `/tmp/dify-canvas/web/app/components/workflow/`（React Flow，API 与 @vue-flow/core 1.48.2 等价）。
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/workflows/execute-plan.md
</execution_context>

<constraints>
- **纯前端**：所有改动只在 `web/` 目录内，绝不动 `server/`。
- **提交纪律**：工作区已有一批与本任务无关的 `server/` 未提交改动。提交时只 `git add` 本任务改过的 `web/` 文件，**禁止** `git add server/`、`git add -A`、`git add .`。
- **代码规范**（遵守 AGENTS.md / `web/eslint.config.ts` @antfu）：注释/文案用中文（zh-CN）；TS 类型完整；不引入 `elkjs`（复用现有 dagre）。
- **i18n**：新增用户可见文案（按钮 tooltip、菜单等）若现有 i18n 体系覆盖则接入，默认中文；工具栏现有按钮多用裸中文字符串，沿用同风格即可。
- **不回归**：保留现有 gradient 视觉体系、undo/redo、对齐辅助线、MiniMap、多选工具栏等既有能力。
</constraints>

<context>
@web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue
@web/src/components/workflow/editor/nodes/DynamicPortNode.vue
@web/src/components/workflow/editor/utils/edgeRouting.ts
@web/src/components/workflow/editor/edges/GradientEdge.vue
@web/src/components/workflow/editor/WorkflowCanvas.vue
@web/src/components/workflow/editor/composables/useWorkflowTransform.ts
@web/src/components/workflow/editor/composables/useConnectionValidator.ts
@web/src/components/workflow/editor/composables/useDragAndDrop.ts
@web/src/composables/useDagreLayout.ts
@web/src/stores/useWorkflowsStore.ts
@web/src/stores/useNodeTypesStore.ts
@web/src/components/workflow/WorkflowToolbar.vue
@web/src/components/workflow/workflowFocus.ts
@web/src/pages/workflows/[id].vue

# dify 参考（只读，照抄设计）
@/tmp/dify-canvas/web/app/components/workflow/custom-edge.tsx
@/tmp/dify-canvas/web/app/components/workflow/custom-connection-line.tsx
@/tmp/dify-canvas/web/app/components/workflow/nodes/_base/components/node-handle.tsx

# 关键事实（已核对，executor 直接用，勿重复探查）
# - @vue-flow/core 1.48.2 导出 BaseEdge / EdgeLabelRenderer / getBezierPath / Position；<VueFlow> 有具名插槽 #connection-line（props: ConnectionLineProps，含 sourceX/sourceY/targetX/targetY/sourcePosition/targetPosition）。
# - Handle 端口集来自 useNodeTypesStore 的 inputs/outputs（D-04，SSOT）；store 未就绪回退 default 单 in/单 out。触发器节点 inputs 为空（见 portConfig.ts TRIGGER_NODE_TYPES / 后端 category==='trigger'）。
# - 边往返：useWorkflowTransform.toVueFlowEdges/fromVueFlowEdges；store 边为 WorkflowEdgeStore（source/target/sourcePort/targetPort/label/condition）。
# - store API：addNode/removeEdge/addEdge 自带 saveToHistory；updateNodePosition 仅 markDirty 不入历史；saveToHistory 手动入历史。
# - fitView 只能在 VueFlow 上下文（WorkflowCanvas）内调用 → 跨兄弟用 workflowFocus 持有器（现有 focusNode 范式）。
# - 既有 popover 组件：web/src/components/ui/popover（reka-ui）。节点视觉/图标：editor/nodes/nodeVisuals。
</context>

<tasks>

<task type="auto">
  <name>Task 1 (P0)：横向 Handle + 单一 0.16 bezier 边（病根修复，最高优先级）</name>
  <files>
web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue,
web/src/components/workflow/editor/nodes/DynamicPortNode.vue,
web/src/components/workflow/editor/utils/edgeRouting.ts,
web/src/components/workflow/editor/edges/GradientEdge.vue,
web/src/components/workflow/editor/edges/CustomConnectionLine.vue,
web/src/components/workflow/editor/WorkflowCanvas.vue,
web/src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts
  </files>
  <action>
照抄 dify 的「Handle 永远 source=Right / target=Left + 单一 bezier curvature 0.16」铁律（P0-1 + P0-2）。

1) BaseWorkflowNode.vue（P0-1）：
   - Input(target) Handle 改 `:position="Position.Left"`；Output(source) Handle 改 `:position="Position.Right"`（替换现在的 Position.Top / Position.Bottom）。
   - 多端口分布从水平改垂直：新增 `portTop(index, total)` 返回 top 百分比（沿用现有 `portLeft` 同样的 `(index+1)/(total+1)*100%` 公式，键名换 `top`），Handle `:style` 由 `{ left: ... }` 改 `{ top: portTop(i, len) }`。可删除 `portLeft` 若不再被引用（避免 eslint 未用告警）。
   - 触发器节点隐藏入 Handle：input Handle 的 `v-show` 增加「inputPorts 非空」条件（即 `inputPorts.length > 0 && hideHandles !== 'input' && hideHandles !== 'both'`）。触发器节点 inputs 为空 → inputPorts 为空 → 不渲染入 Handle。参考 /tmp/dify-canvas/.../node-handle.tsx（NodeTargetHandle 用 Position.Left、NodeSourceHandle 用 Position.Right）。

2) DynamicPortNode.vue（P0-1）：
   - 动态 Handle 的 `:position` 从 `Position.Bottom`(parallel)/`Position.Top`(join) 改为 `parallel ? Position.Right : Position.Left`（parallel 是 source 在右，join 是 target 在左）。
   - `portLeft` 改为 `portTop`（垂直均分），Handle `:style` 由 `{ left: ... }` 改 `{ top: ... }`。

3) edgeRouting.ts（P0-2）：删除 horizontal-bezier / return-bezier / smooth-step 三分支自适应逻辑。改为单一实现：
   `getBezierPath({ sourceX: sourceX - 8, sourceY, sourcePosition: Position.Right, targetX: targetX + 8, targetY, targetPosition: Position.Left, curvature: 0.16 })`，返回 `{ path, labelX, labelY }`。可删除 `EdgeRouteResult.strategy` 字段与 getSmoothStepPath 导入。注释说明照抄 dify custom-edge.tsx。

4) GradientEdge.vue（P0-2）：strokeWidth 固定为 2（选中态可微调，如 2.5，但默认 2，去掉旧的 selected?3:2 也可——保留 gradient/选中发光视觉）。保留现有 linearGradient + 选中 drop-shadow 视觉。`animated` 边维持虚线动画。路径继续取 `getWorkflowEdgeRoute(...)`（已是单一 bezier）。

5) CustomConnectionLine.vue（新建，P0-2）：拖拽连线组件，照抄 /tmp/dify-canvas/.../custom-connection-line.tsx。`<script setup lang="ts">` defineProps<ConnectionLineProps>()（从 @vue-flow/core 引类型），computed 调用 `getBezierPath({ sourceX, sourceY, sourcePosition: Position.Right, targetX, targetY, targetPosition: Position.Left, curvature: 0.16 })`，模板渲染 `<path fill="none" stroke 虚线/默认色 stroke-width=2 :d="path" />`（可加一个目标端小竖条 rect）。保证拖拽与连成后形状一致。

6) WorkflowCanvas.vue（P0-2）：用具名插槽接入拖拽连线 —— `<template #connection-line="props"><CustomConnectionLine v-bind="props" /></template>`，并 import 新组件。

7) BaseWorkflowNode.test.ts：扩断言（Handle stub 已暴露 position prop）。新增/修改：
   - 断言 input Handle position==='left'、output Handle position==='right'；
   - 新增用例：触发器（store 中 inputs:[] 的 node_type，category:'trigger'）不渲染 target Handle（handleIds(target) 为空）。
   保持现有 default 回退 / 后端端口 / 审批 approved·rejected 三个用例通过。

注意：本任务是消灭「连线飘」的命门——改完 Handle 方向与边方向必须一致（都横向 L→R），不得遗留任一处仍用 Top/Bottom。
  </action>
  <verify>
    <automated>cd web && pnpm vitest run src/components/workflow/editor/nodes/__tests__/BaseWorkflowNode.test.ts</automated>
    <automated>cd web && pnpm type-check</automated>
  </verify>
  <done>edgeRouting.ts 仅剩单一 getBezierPath(Right/Left,0.16)；BaseWorkflowNode/DynamicPortNode 的 Handle 全部 Left/Right + 垂直分布；触发器无入 Handle；CustomConnectionLine 接入 #connection-line 且与边同参数；BaseWorkflowNode.test.ts 全绿；type-check 通过。</done>
</task>

<task type="auto">
  <name>Task 2 (P1)：一键自动布局（横向 LR）+ 边中点 "+" 插入节点</name>
  <files>
web/src/components/workflow/editor/composables/useAutoLayout.ts,
web/src/components/workflow/workflowFocus.ts,
web/src/components/workflow/editor/WorkflowCanvas.vue,
web/src/components/workflow/WorkflowToolbar.vue,
web/src/pages/workflows/[id].vue,
web/src/components/workflow/editor/NodeInsertMenu.vue,
web/src/components/workflow/editor/edges/GradientEdge.vue,
web/src/components/workflow/editor/composables/useDragAndDrop.ts,
web/src/components/workflow/editor/composables/__tests__/useDragAndDrop.test.ts
  </files>
  <action>
P1-3 自动布局 + P1-4 边中点插入。

A) useAutoLayout.ts（新建，P1-3）：composable `useAutoLayout()` 暴露 `applyAutoLayout()`：
   - 用 `useDagreLayout().applyLayout(toVueFlowNodes(store.nodes), toVueFlowEdges(store.edges), { rankdir: 'LR', ranksep: 80, nodesep: 40 })` 计算新坐标（复用既有 dagre，rankdir 传 'LR' 横向）。
   - 把新 position 写回 store：遍历结果 `store.updateNodePosition(node.id, node.position)`（仅 markDirty 不入历史），最后**手动 `store.saveToHistory()` 一次**，使整次布局成为单步可撤销（不要每个节点都入历史）。
   - 返回布局是否有节点（空图直接返回）。fitView 不在此（无 VueFlow 上下文），由 WorkflowCanvas 调用方在布局后触发。

B) workflowFocus.ts（P1-3 跨兄弟接线）：`WorkflowFocusContext` 增加可选成员 `autoLayout: (() => void) | null`（沿用 focusNode 同样的持有器范式，未就绪 no-op）。

C) WorkflowCanvas.vue（P1-3）：import useAutoLayout；实现 `function runAutoLayout() { const has = applyAutoLayout(); if (has) fitView({ duration: 300 }) }`；像现有 focusNode 一样把 `workflowFocus.autoLayout = runAutoLayout`（挂载时写入，onBeforeUnmount 置 null）。

D) WorkflowToolbar.vue（P1-3）：在「撤销/重做」附近加一个「自动布局/整理」按钮（lucide 图标如 `LayoutGrid` 或 `Network`，带 Tooltip「自动整理布局」），`@click="emit('autoLayout')"`；emits 增加 `(e: 'autoLayout'): void`。

E) [id].vue（P1-3）：监听 `@auto-layout`（模板事件名 kebab：`@auto-layout="onAutoLayout"`），`onAutoLayout()` 调 `workflowFocus.autoLayout?.()`（workflowFocus 已 provide）。

F) NodeInsertMenu.vue（新建，P1-4 + 供 P2-6 复用）：可复用节点选择 popover。用 `~/components/ui/popover`（Popover/PopoverTrigger/PopoverContent）。props: `{ triggerClass?: string }`，slot 自定义触发器（默认渲染一个圆形 "+" 按钮）；内部列出 `useNodeTypesStore().nodeTypesByCategory` 的节点（图标用 nodeVisuals，名称 display_name，按分类分组，可加搜索框可选），点击某节点 `emit('select', nodeType)` 并关闭 popover。纯 UI + 选择事件，不直接改 store（插入逻辑由调用方处理，保持可复用）。

G) GradientEdge.vue（P1-4）：用 EdgeLabelRenderer 在 bezier 中点放 hover 才显形的 "+"，照抄 /tmp/dify-canvas/.../custom-edge.tsx 的 EdgeLabelRenderer + handleInsert：
   - import { EdgeLabelRenderer } from '@vue-flow/core'，import NodeInsertMenu。
   - 用本地 ref 跟踪 hover（mouseenter/mouseleave）控制 "+" 透明度/pointer-events；`<EdgeLabelRenderer><div :style="{ position:'absolute', transform: 'translate(-50%,-50%) translate(${labelX}px,${labelY}px)', pointerEvents: visible?'all':'none', opacity: visible?1:0 }" class="nopan nodrag"><NodeInsertMenu @select="onInsert" /></div></EdgeLabelRenderer>`。
   - `onInsert(nodeType)`：在该边中间插入新节点——复用「删旧边 + 加新节点 + 两条新边」逻辑（与 useDragAndDrop 现有插入实现同形）：`store.removeEdge(props.id)` → `store.addNode({...})`（id randomUUID、shortId generateShortId、position 取边中点对应 flow 坐标——可用节点当前 source/target position 的中点近似，或直接用 props.sourceX/targetX 经 screenToFlowCoordinate 反算；优先用两端节点 position 中点，避免坐标系换算复杂）→ 两条新边 `source→新节点`(sourcePort 取 props.sourceHandle ?? 'default')、`新节点→target`(targetPort 取 props.targetHandle ?? 'default')。node 默认字段对齐 useDragAndDrop 现有 newNode 形状（onError 'abort'、retryTimes 0 等）。

H) useDragAndDrop.ts（P1-4）：删除「用直线距离 pointToLineDistance 判定命中连线并插入」的旧逻辑（曲线对不准）——`onDrop` 简化为：始终直接 `store.addNode(...)` + recordRecentNode（移除 hitEdge 分支、pointToLineDistance、EDGE_HIT_TOLERANCE）。边中插入改由 G 的边 "+" 按钮承担。

I) useDragAndDrop.test.ts（配合 H 更新）：移除/改写依赖旧命中逻辑的用例（`pointToLineDistance 对照实现`整组、`落点在 edge 上...插入`、`多条 edge 命中最近`）。保留并确认仍通过：无 edge 直接 addNode（现在所有 drop 都走此路径）、onDragOver、recordRecentNode 副作用、getRecentNodes。新增断言：有 edge 存在时 drop 也只 addNode、不再 removeEdge/addEdge（确认旧插入逻辑已移除）。

注意 import 卫生：删掉不再使用的符号（GraphEdge、getNodeDefinition 若仍用于 def 默认值则保留）。eslint @antfu 会报未用变量需清理。
  </action>
  <verify>
    <automated>cd web && pnpm vitest run src/components/workflow/editor/composables/__tests__/useDragAndDrop.test.ts</automated>
    <automated>cd web && pnpm type-check</automated>
    <automated>cd web && pnpm lint</automated>
  </verify>
  <done>工具栏出现「自动整理布局」按钮，点击经 workflowFocus.autoLayout 触发横向 LR 重排 + fitView 且单步可撤销；NodeInsertMenu 可选节点；悬停边中点显形 "+"，选节点后删旧边+加节点+两条新边；useDragAndDrop 不再有曲线直线命中逻辑且其测试全绿；type-check / lint 通过。</done>
</task>

<task type="auto">
  <name>Task 3 (P2–P3)：边四元组 ID + sourceType/targetType + 四元组重复校验 + Handle 内嵌加节点 + 分支出边排序</name>
  <files>
web/src/components/workflow/editor/composables/useWorkflowTransform.ts,
web/src/components/workflow/editor/composables/useConnectionValidator.ts,
web/src/components/workflow/editor/WorkflowCanvas.vue,
web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue,
web/src/components/workflow/editor/composables/useAutoLayout.ts
  </files>
  <action>
P2-5 + P2-6 + P3-7。

A) useWorkflowTransform.ts（P2-5）：在 `toVueFlowEdges` 的 edge `data` 上增加 `sourceType`/`targetType`（两端节点类型）。由于 `toVueFlowEdges` 当前只收 storeEdges，需要节点类型映射 —— 给 `toVueFlowEdges(storeEdges, storeNodes?)` 增加可选第二参 `storeNodes`，内部建 `Map<id, nodeType>`，对每条边写 `data.sourceType = map.get(edge.source)`、`data.targetType = map.get(edge.target)`（取不到留 undefined）。更新 `WorkflowEdgeData` 接口加 `sourceType?: string; targetType?: string`。`fromVueFlowEdges` 无需回写这两个派生字段（不入 store，store 边模型不变，避免污染后端契约）。更新 WorkflowCanvas 中 `toVueFlowEdges(storeEdges.value)` 调用为 `toVueFlowEdges(storeEdges.value, storeNodes.value)`。
   - 备注：sourceType/targetType 供边 "+" 菜单未来按上下游类型过滤可选节点用（dify availablePrevBlocks/NextBlocks）；本任务先填充数据，若 NodeInsertMenu 要按类型过滤可选做、否则展示全量即可。

B) useConnectionValidator.ts（P2-5）：把重复边判定从 `e.source===source && e.target===target` 改为带 handle 的四元组比对：
   `e.source===c.source && e.sourceHandle===c.sourceHandle && e.target===c.target && e.targetHandle===c.targetHandle`（注意 connection 的 handle 字段名为 `sourceHandle`/`targetHandle`，可能为 null，与边的 sourceHandle/targetHandle 比对前统一 `?? 'default'` 归一）。修复「同两节点不同分支端口的多条边被误报重复」。防自连接/防环逻辑保持不变。
   - 同步检查 WorkflowCanvas `onConnect` 生成的 edge id `edge-${source}-${target}-${Date.now()}` 已含时间戳天然唯一，可保留；如需更稳可改为含 handle 的四元组拼接 `edge-${source}-${sourceHandle}-${target}-${targetHandle}-${Date.now()}`（可选）。

C) BaseWorkflowNode.vue（P2-6）：hover 节点时，在出/入 Handle 旁浮出 "+"，复用 Task 2 的 NodeInsertMenu。点击在该方向追加并自动连线一个新节点：
   - 出方向(右)："+" 触发 NodeInsertMenu，选节点后：新节点 position 放在本节点右侧（x + 约 280，y 同本节点），`store.addNode(newNode)` + `store.addEdge({ source: 本节点 id, sourcePort: 第一个 output 端口 id ?? 'default', target: 新节点 id, targetPort: 'default', ... })`。
   - 入方向(左)：对称，新节点放左侧，边方向 新节点→本节点。
   - 用 group-hover 控制 "+" 显隐（节点根 div 已有 `group` class）。绝不影响既有 NodeToolbar / 拖拽。触发器节点（无入端口）不显示入方向 "+"。
   - 这两处「加节点 + 连线」可抽一个小 helper（如本组件内 `appendNode(direction, nodeType)`）避免重复。

D) useAutoLayout.ts（P3-7 分支出边排序）：自动布局时，让同一源节点的分支出边按业务顺序稳定排列（如 condition 的 else/默认分支殿后、parallel 按 branch 序）。参考 /tmp/dify-canvas/.../utils/elk-layout.ts 的 sortIfElseOutEdges 思路：在 applyLayout 前对传给 dagre 的 edges 做稳定排序（按 sourceHandle 名排序，把 'else'/'false'/'default' 之类兜底分支排到最后），使 dagre 分层时分支上下顺序稳定。实现为 useAutoLayout 内部一个纯函数 `sortBranchEdges(edges)`，仅影响布局输入顺序、不改 store 边。

E) P3 端口 ID 对齐后端（**标为可延后项 / 视成本决定**）：
   已知 DynamicPortNode 端口 ID 用 `port-1` / `port-${Date.now()}`，但后端 parallel 期望 `branch_0/branch_1`、condition 期望 `branch_0.../else`，且端口增删经 `useVueFlow().updateNodeData` 未回写 Pinia store（刷新/保存会丢）。
   - 若成本可控：把 DynamicPortNode 默认端口与 addPort 命名对齐后端（parallel → `branch_0/branch_1/...` 递增；join → `input_0/input_1/...`，对齐 portConfig.ts getDefaultPortsForNodeType），并把端口增删改为经 `store.updateNode(id, {...})` 回写 Pinia（当前用 useVueFlow updateNodeData 不进 store/历史）。
   - 若成本高（涉及后端契约/迁移面）：**本任务不做**，在 SUMMARY 中明确标注为延后项，不要半改留下不一致状态。
   - 决策原则：本 quick 任务核心是「连线交互对标 dify」，端口 ID 对齐是附带项，宁可干净延后也不引入半成品。
  </action>
  <verify>
    <automated>cd web && pnpm vitest run src/components/workflow/editor</automated>
    <automated>cd web && pnpm type-check</automated>
    <automated>cd web && pnpm lint</automated>
  </verify>
  <done>边 data 带 sourceType/targetType；同两节点不同分支端口的边不再误报重复（防自连/防环不回归）；节点 hover 出/入 Handle 旁可 "+" 加节点并自动连线，触发器无入向 "+"；自动布局分支出边顺序稳定；P3 端口 ID 对齐按成本决策并在 SUMMARY 如实标注；editor 目录 vitest + type-check + lint 全绿。</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>横向 L→R 画布：Handle 全部左入右出、单一 0.16 bezier 连线（拖拽与连成一致）、一键自动布局、边中点 "+" 插入、Handle 旁 "+" 加节点、四元组重复边校验。</what-built>
  <how-to-verify>
1. 启动前端：`pnpm -C web dev`，打开任一工作流编辑页 `/workflows/{id}`。
2. 观察连线：所有边从节点右侧出、左侧入，呈柔和 bezier，无折返/无"飘"；拖拽新连线时虚线与最终实线形状一致。
3. 触发器节点（如 manual_trigger）左侧无入 Handle。
4. 点工具栏「自动整理布局」：节点横向 L→R 重排并居中；按撤销(Undo)能一步还原。
5. 悬停某条连线中点出现 "+"，点击选一个节点，原边断开、中间插入新节点并接好两条边。
6. 悬停节点，右侧 "+" 出现，点击选节点，在右侧追加并自动连线。
7. 从一个 parallel/condition 节点的不同分支端口连到同一目标，不再提示"已存在连接"。
  </how-to-verify>
  <resume-signal>回复"approved"或描述问题</resume-signal>
</task>

</tasks>

<verification>
- `pnpm -C web type-check` 通过（vue-tsc --noEmit）。
- `pnpm -C web lint` 通过（@antfu eslint）。
- `pnpm -C web vitest run src/components/workflow/editor` 全绿（BaseWorkflowNode、useDragAndDrop 等更新后通过）。
- `pnpm -C web build`（vue-tsc -b && vite build）可成功（最终把关，可选但推荐）。
- grep 确认 edgeRouting.ts / GradientEdge.vue / CustomConnectionLine.vue 无任何 `Position.Top` / `Position.Bottom`；BaseWorkflowNode/DynamicPortNode 的 Handle position 仅 Left/Right。
</verification>

<success_criteria>
- 连线方向与 Handle 方向一致（均横向 L→R），"连线飘"病根消除。
- 仅一种 bezier（curvature 0.16），拖拽连线与连成后一致。
- 自动布局、边中点插入、Handle 加节点、四元组校验均可用且不回归既有能力。
- 全部改动限于 web/；提交仅 add 本任务 web/ 文件，未触碰 server/。
</success_criteria>

<output>
完成后创建 `.planning/quick/260621-dwn-dify-right-left-handle-bezier-curvature0/260621-dwn-SUMMARY.md`，记录：实际改动文件、P3 端口 ID 对齐的决策（做了/延后及原因）、人工验收结果。
提交：`git add` 仅限本任务改过的 `web/` 文件后 `git commit`（中文 Conventional Commits，如 `feat(workflow): 画布对标 dify 横向 Handle 与单一 bezier 连线`）。**禁止** `git add -A` / `git add server/`。
</output>
