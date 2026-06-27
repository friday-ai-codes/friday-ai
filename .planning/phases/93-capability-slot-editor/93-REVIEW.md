---
phase: 93-capability-slot-editor
reviewed: 2026-06-27T13:50:00Z
depth: deep
files_reviewed: 12
files_reviewed_list:
  - server/workflows/api/serializers.py
  - web/src/stores/useNodeTypesStore.ts
  - web/src/stores/useWorkflowsStore.ts
  - web/src/components/workflow/editor/composables/portShapes.ts
  - web/src/components/workflow/editor/composables/useConnectionValidator.ts
  - web/src/components/workflow/editor/composables/useConnectionDragState.ts
  - web/src/components/workflow/editor/composables/usePortSnap.ts
  - web/src/components/workflow/editor/composables/useImCapability.ts
  - web/src/components/workflow/editor/composables/useWorkflowTransform.ts
  - web/src/components/workflow/editor/composables/useAutoLayout.ts
  - web/src/components/workflow/editor/nodes/BaseWorkflowNode.vue
  - web/src/components/workflow/editor/nodes/nodeVisuals.ts
  - web/src/components/workflow/editor/WorkflowCanvas.vue
  - web/src/components/workflow/editor/edges/CustomConnectionLine.vue
  - web/src/components/workflow/sidebar/NodePalette.vue
  - web/src/locales/zh-CN.json
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: resolved
resolution:
  resolved_at: 2026-06-27T14:10:00Z
  resolved: [WR-01, WR-02, WR-03, IN-01, IN-02]
  deferred: []
  notes: 全部 3 个 WARNING 与 2 个 INFO 已修复并各自原子提交；vitest（editor + store 97 通过）/ vue-tsc / 受改文件 eslint 均通过，既有编辑器零回归。
---

# Phase 93: Code Review Report

**Reviewed:** 2026-06-27T13:50:00Z
**Depth:** deep
**Files Reviewed:** 16 (source files; co-located `__tests__` 未单列)
**Status:** issues_found

## Summary

逐文件 + 跨文件审查了 93-00~93-06 的全部源改动（后端 `serializers.py` 暴露 `shape`，前端契约判定 / 磁吸 / 附着编组 / IM 门控 / i18n / palette）。

整体质量高，重点项基本达标：
- **SLOT-03 同口径**：`arePortShapesCompatible` 与后端 `_validate_port_shapes` 一致（空通配放行）；前端仅即时判定、后端仍权威；`onConnect` 吸附命中后**重新** `getValidationError(effective, t)`，吸附不绕合法性；`PORT_SNAP_THRESHOLD=28` 为独立常量，未触碰 `SNAP_THRESHOLD=5`/`snap-grid=[15,15]`。✅
- **SLOT-04 持久化**：父子关系仅经既有 `metadata.parentNodeId` JSON 列持久化（零后端 schema 变更），`toBackendNodes` 透传 metadata；`toVueFlowNodes` 同源派生 `parentNode/extent` 且不删改 metadata；父先子两趟稳定排序。`removeNode` 级联删子+连边，`detachChild` `delete` 键往返不残留。编组容器为 `attachGroups` 单一实现。✅
- **i18n / shape 友好名**：`zh-CN.json` 新增 `workflow.*` 键为真实中文，且**无重复 top-level `workflow` 键**（已用 Python `object_pairs_hook` 校验，JSON 解析正常，未覆盖既有翻译）；后端实际声明的 3 个 shape（`clarification_request/answer`、`feishu_message`）在 `SHAPE_DISPLAY_KEY` 均有中文映射，吸附/拒绝 Toast **不会泄漏英文标识符**。✅
- **安全**：门控/吸附/高亮均为前端引导，后端节点执行期仍校验必填，无凭证/敏感数据前端泄漏。✅

发现 3 个 WARNING（其中 IM 门控存在**误门控**逻辑错误）与 2 个 INFO。无 BLOCKER。

## Warnings

### WR-01: IM 门控误锁 `notify_feishu`（基于 webhook，与 chat_id/IM 源无关）

> **[RESOLVED]** `IM_DEPENDENT_TYPES` 收敛为仅 `notify_feishu_im`（移除 webhook 型
> `notify_feishu`）；`isImGated(nodeType, config?)` 改为按 config 判定：仅"发群
> `chat_id` 模式 + 节点未配置 `receive_id` + 图无 IM 源"时门控，发个人（open_id/user_id）
> 或已填字面/变量化 `receive_id` 不误报。`BaseWorkflowNode` 透传 `data.config`，补/更新单测。
> Commit `fc40b2708`。

**File:** `web/src/components/workflow/editor/composables/useImCapability.ts:23`
**Issue:**
`IM_DEPENDENT_TYPES = new Set(['notify_feishu', 'notify_feishu_im'])`，当图中无 `create_group_chat`/`create_work_item_chat` 时这两类节点被视为缺 chat_id 源而门控（卡片 `opacity-40` + 锁徽标 + `not-allowed`）。但核对后端节点 schema：
- **`notify_feishu`**（`server/workflows/nodes/integrations/feishu.py:17`）`config_schema.required = ["webhook_url", "content"]`，走**飞书机器人 Webhook**，**完全不依赖 chat_id**，与 IM 源节点无任何关系。把它纳入 IM 门控属于**误门控**——一个本可独立正常工作的节点被视觉禁用，误导用户去添加并不需要的「创建群聊」节点。
- **`notify_feishu_im`**（`feishu_im_notify.py:38`）`receive_id_type` 枚举为 `chat_id | open_id | user_id`，可发个人（open_id/user_id）或填入字面/模板化 `receive_id`，无需 `create_group_chat` 节点。仅凭「图中是否存在 IM 源节点」一刀切门控，对发个人 / 变量化 chat_id（如来自 `fetch_group_chat`）等合法场景会产生误报。

门控仅视觉降级、不阻断后端执行也不阻断连线，故非 BLOCKER；但 `notify_feishu` 的纳入是明确的逻辑错误，且与 CONTEXT 决策 D「具备 chat_id 目标才可用」语义不符。
**Fix:**
```ts
// 移除 webhook 型 notify_feishu；notify_feishu_im 至少改为软提示或仅在
// receive_id_type 隐含 chat_id 且确无来源时门控（更稳妥：保留软提示，不做硬视觉禁用）。
export const IM_DEPENDENT_TYPES = new Set(['notify_feishu_im'])
```
若产品确需对 `notify_feishu_im` 门控，建议结合该节点 `config.receive_id_type` 判断（仅 `chat_id` 模式且无来源时提示），而非按类型一刀切。

### WR-02: 批量删除多个「带附着子」父节点时静默丢删（单一 `pendingDelete` 被覆盖）

> **[RESOLVED]** `pendingDelete` 由单一 `{id}` 改为批量 `{ids[]}` 聚合确认：
> `requestRemoveNode` 多次调用时带子父节点逐个聚合（去重、累加子计数）而非互相覆盖，
> `confirmDelete` 循环删除全部父节点（各自级联子）。新增 `deleteWithChildBatchBody`
> i18n 键与 `deleteDialogBody` 区分单/多父展示。补 WR-02 单测（聚合 + 去重）。
> Commit `de64d7291`。

**File:** `web/src/components/workflow/editor/WorkflowCanvas.vue:492`（`handleBatchDelete`）/ `:422`（`requestRemoveNode`）
**Issue:**
`handleBatchDelete` 对每个选中 id 调用 `requestRemoveNode(id)`；对「带附着子」的节点，`requestRemoveNode` 写入**单一** `pendingDelete` ref：
```ts
function requestRemoveNode(id: string) {
  const count = store.getChildNodes(id).length
  if (count > 0) {
    pendingDelete.value = { id, name, count } // 多个时互相覆盖
  } else {
    store.removeNode(id) // 无子者立即删
  }
}
```
当一次框选包含 ≥2 个带附着子的父节点时，只有**最后一个**的 `pendingDelete` 存活；确认后仅删该节点，先前带子父节点的删除意图被静默丢弃；而同批无子节点已立即删除 → 形成「部分删除」的困惑结果（非数据丢失，但与用户意图不符）。
**Fix:** 批量场景聚合为一次确认（收集所有带子 id + 总数），确认后统一删除；或将 `pendingDelete` 改为队列依次确认：
```ts
function handleBatchDelete() {
  const ids = getSelectedNodes.value.map(n => n.id)
  const withChildren = ids.filter(id => store.getChildNodes(id).length > 0)
  ids.filter(id => store.getChildNodes(id).length === 0).forEach(id => store.removeNode(id))
  if (withChildren.length) {
    const totalChildren = withChildren.reduce((s, id) => s + store.getChildNodes(id).length, 0)
    pendingDelete.value = { ids: withChildren, count: totalChildren } // 聚合确认
  }
}
```

### WR-03: 取消级联删除确认后画布可能与 store 短暂失同步

> **[RESOLVED]** 新增 `canvasSyncVersion` 版本号纳入 `vfNodes` 计算依赖，`cancelDelete`
> 时 bump 强制 `vfNodes` 产出新数组引用，触发 Vue Flow 从 store 重灌内部节点，恢复
> 画布/store 同步。补 WR-03 单测（取消后节点仍渲染于画布且 store 保留父子）。
> Commit `c8a1db5e1`。

**File:** `web/src/components/workflow/editor/WorkflowCanvas.vue:138`（`onNodesChange` remove 分支）→ `requestRemoveNode`
**Issue:**
`@nodes-change` 的 `remove` 变更现改为 `requestRemoveNode`，对带子父节点**延后**删除（仅置 `pendingDelete`，不改 store）。但 `<VueFlow>` 未显式 `:apply-default="false"`（默认 `applyDefault=true`），Vue Flow 会在发出 `remove` 变更的同时把该节点从其**内部状态**移除；而 `:nodes="vfNodes"` 是单向 computed，仅在 `storeNodes/storeEdges` 变化时重算。若用户在确认框点「取消」，store 未变 → `vfNodes` 引用不变 → Vue Flow 不会被重新喂入 → 节点已从画布消失但仍在 store 中，直到下次任意 store 变更（如移动其他节点）才自愈重现。期间存在画布/store 失同步（保存时该节点仍会被写回但不可见）。
**Fix:** 对「带子父节点」拦截在删除发生**之前**（如不在 `onNodesChange` 依赖 Vue Flow 默认删除，而在键盘/工具栏入口先确认再触发删除）；或取消时强制重渲染（替换 `vfNodes` 引用 / 调 Vue Flow `setNodes`）。建议补一条单测：选中带子父节点→触发 remove→取消→断言节点仍渲染于画布。

## Info

### IN-01: 删除确认弹窗标题/按钮硬编码中文，未用新增 i18n 键

> **[RESOLVED]** 新增 `workflow.editor.slot.deleteTitle/cancel/delete` 键，级联删除弹窗
> 标题与「取消」「删除」按钮、解除附着弹窗「取消」按钮统一改走 `t()`。Commit `8207cdf70`。

**File:** `web/src/components/workflow/editor/WorkflowCanvas.vue:669-685`
**Issue:** 级联删除弹窗 `<AlertDialogTitle>删除节点</AlertDialogTitle>`、`取消`、`删除` 与解除弹窗的 `取消` 仍硬编码；而本 phase 已为 slot 引入 i18n 命名空间（`deleteWithChildBody`/`detachBody` 等已用 `t()`）。与既有「编辑器文案多硬编码」习惯一致、无英文泄漏，故非回归；但同一弹窗内 i18n 用法不一致。
**Fix:** 复用/新增 `workflow.editor.slot.*`（如 `deleteTitle`/`common.cancel`/`common.delete`）统一走 `t()`。

### IN-02: `detachChild` 对 `metadata` 解构缺空值防御

> **[RESOLVED]** 解构改用 `(node.metadata ?? {})`，与 `attachChild` spread 防御一致。
> Commit `46256d8c5`。

**File:** `web/src/stores/useWorkflowsStore.ts:636`
**Issue:** `const { parentNodeId: _drop, ...rest } = node.metadata as Record<string, unknown>`；若 `node.metadata` 为 `undefined/null` 将抛 `TypeError`。当前 `detachChild` 仅作用于已附着节点（`metadata.parentNodeId` 必为对象），实际安全；但与 `attachChild` 的 `{ ...node.metadata, ... }`（spread 对 undefined 安全）相比防御性不一致。
**Fix:** `const { parentNodeId: _drop, ...rest } = (node.metadata ?? {}) as Record<string, unknown>`。

---

_Reviewed: 2026-06-27T13:50:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
