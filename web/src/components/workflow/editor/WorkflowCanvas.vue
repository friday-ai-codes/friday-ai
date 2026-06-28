<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * 数据同步策略：Pinia store 是 source of truth，通过 :nodes/:edges 单向传入 VueFlow。
 * VueFlow 的所有内部变更（拖拽、删除等）通过 @nodes-change/@edges-change 统一回写 store。
 */
import type { Connection, EdgeChange, Node, NodeChange, NodeMouseEvent } from '@vue-flow/core'
import type { SnapCandidate, SnapTarget } from './composables/usePortSnap'
import type { WorkflowNodeStore } from '~/types/workflow/store'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { ConnectionMode, Panel, SelectionMode, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { Copy, Trash2, Waypoints } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, inject, markRaw, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { WorkflowFocusKey } from '~/components/workflow/workflowFocus'
import { useToast } from '~/composables/useToast'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'
import { resolvePortShape } from './composables/portShapes'
import { useAlignmentGuides } from './composables/useAlignmentGuides'
import { useAutoLayout } from './composables/useAutoLayout'
import { useConnectionDragState } from './composables/useConnectionDragState'
import { getValidationError, useConnectionValidator } from './composables/useConnectionValidator'
import { useDragAndDrop } from './composables/useDragAndDrop'
import { useKeyboardShortcuts } from './composables/useKeyboardShortcuts'
import { findSnapTarget } from './composables/usePortSnap'
import { SIGNAL_EDGE_TYPE, useSignalLayer } from './composables/useSignalLayer'
import { toVueFlowEdges, toVueFlowNodes } from './composables/useWorkflowTransform'
import CustomConnectionLine from './edges/CustomConnectionLine.vue'
import GradientEdge from './edges/GradientEdge.vue'
import SignalSubscriptionEdge from './edges/SignalSubscriptionEdge.vue'
import { nodeTypes } from './nodes'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'

const store = useWorkflowsStore()
const { nodes: storeNodes, edges: storeEdges } = storeToRefs(store)

/**
 * WR-03：取消级联删除后强制重灌 `:nodes` 用的版本号。
 * Vue Flow `applyDefault` 默认在发出 remove 变更时已把节点从其内部状态移除；带附着子的
 * 父节点删除被延后（仅置 pendingDelete，store 未变），若用户点「取消」，store 不变 →
 * `vfNodes` 引用不变 → Vue Flow 不会被重新喂入 → 节点已从画布消失却仍在 store（失同步）。
 * bump 本版本号即可让 `vfNodes` 产出新数组引用，触发 Vue Flow 从 store 重新同步内部节点。
 */
const canvasSyncVersion = ref(0)

// ============================================================================
// P6 画布双层视图：信号层开关 + 虚线信号订阅边（纯派生叠加，reaction 配置为准）。
// 关闭时画布与现状完全一致；开启时叠加「宿主 → 通知/文档」虚线订阅边 + surfaced 目标节点。
// ============================================================================

/** 信号层开关：false=只看交付流（默认，与现状一致）；true=叠加信号订阅层。 */
const signalLayerEnabled = ref(false)
function toggleSignalLayer() {
  signalLayerEnabled.value = !signalLayerEnabled.value
}

const { signalEdges, signalTargetIds } = useSignalLayer(storeNodes, signalLayerEnabled)

/**
 * 信号层「可视化目标」节点：把被折叠为卡内 chip 的 notification/document 附着子，
 * 在信号层开启时 surfaced 为画布节点（虚线订阅边的落点）。绝对坐标 = 宿主绝对 + 子相对。
 * 关闭时为空（不入 vfNodes，画布与现状一致）。
 */
const signalTargetNodes = computed<Node[]>(() => {
  if (!signalLayerEnabled.value)
    return []
  const byId = new Map(storeNodes.value.map(n => [n.id, n]))
  const result: Node[] = []
  for (const id of signalTargetIds.value) {
    const child = byId.get(id)
    if (!child)
      continue
    const parentId = child.metadata?.parentNodeId as string | undefined
    const parent = parentId ? byId.get(parentId) : undefined
    const abs = parent
      ? {
          x: (parent.position?.x ?? 0) + (child.position?.x ?? 0),
          y: (parent.position?.y ?? 0) + (child.position?.y ?? 0),
        }
      : { ...child.position }
    result.push({
      id: child.id,
      type: child.nodeType,
      position: abs,
      // 标记为信号层 surfaced 节点：弱化样式，与交付层节点区分（不改 BaseWorkflowNode）。
      class: 'signal-surfaced-node',
      selectable: false,
      data: {
        nodeType: child.nodeType,
        shortId: child.shortId,
        name: child.name,
        description: child.description,
        config: child.config,
        onError: child.onError,
        retryTimes: child.retryTimes,
        retryDelay: child.retryDelay,
        nodeTimeoutSeconds: child.nodeTimeoutSeconds,
        fallbackValues: child.fallbackValues,
        runCondition: child.runCondition,
        metadata: child.metadata,
      },
    })
  }
  return result
})

const vfNodes = computed(() => {
  // 依赖 canvasSyncVersion：取消级联删除时 bump 以强制 Vue Flow 重灌 :nodes（WR-03）。
  void canvasSyncVersion.value
  const base = toVueFlowNodes(storeNodes.value)
  return signalLayerEnabled.value ? [...base, ...signalTargetNodes.value] : base
})
const deliveryEdges = computed(() => toVueFlowEdges(storeEdges.value, storeNodes.value))
/** 传给 VueFlow 的边：交付边 + （信号层开启时）虚线信号订阅边。 */
const vfEdges = computed(() =>
  signalLayerEnabled.value ? [...deliveryEdges.value, ...signalEdges.value] : deliveryEdges.value,
)

const edgeTypes = {
  gradient: markRaw(GradientEdge),
  [SIGNAL_EDGE_TYPE]: markRaw(SignalSubscriptionEdge),
}

const nodeTypesStore = useNodeTypesStore()
const { error: showError } = useToast()
const { t } = useI18n()
const {
  getSelectedNodes,
  fitView,
  viewport: vfViewport,
  getNodes,
  findNode,
  screenToFlowCoordinate,
} = useVueFlow()
const { validateConnection } = useConnectionValidator()
const {
  dragging: connectDragging,
  source: connectSource,
  startConnect,
  endConnect,
  isCompatibleTarget,
} = useConnectionDragState()
const { applyAutoLayout } = useAutoLayout()
const { onDragOver, onDrop } = useDragAndDrop()
const { alignmentGuides, checkAlignment, clearGuides } = useAlignmentGuides()
useKeyboardShortcuts()

/** 是否正在拖拽节点 —— 对齐参考线仅在拖拽过程中显示，松手即清除（避免常驻虚线） */
const isDragging = ref(false)
function onNodeDragStart() {
  isDragging.value = true
}
function onNodeDragStop() {
  isDragging.value = false
  clearGuides()
}

/** 将对齐参考线的 flow 坐标转换为屏幕坐标 */
const guideLines = computed(() => {
  const { x, y, zoom } = vfViewport.value
  return alignmentGuides.value.map((guide) => {
    if (guide.orientation === 'vertical') {
      const screenX = guide.position * zoom + x
      return {
        x1: screenX,
        y1: -10000,
        x2: screenX,
        y2: 10000,
      }
    }
    else {
      const screenY = guide.position * zoom + y
      return {
        x1: -10000,
        y1: screenY,
        x2: 10000,
        y2: screenY,
      }
    }
  })
})

/** 多选节点数量 */
const multiSelectCount = computed(() => getSelectedNodes.value.length)

/**
 * 统一处理 VueFlow 内部节点变更，回写到 Pinia store。
 * 只处理 position（拖拽结束）和 remove（删除），其余忽略。
 */
function onNodesChange(changes: NodeChange[]) {
  for (const change of changes) {
    if (change.type === 'position' && change.position) {
      if (change.dragging) {
        // 拖拽中：检测对齐辅助线并吸附
        const result = checkAlignment(change.id, change.position)
        change.position.x = result.x
        change.position.y = result.y
      }
      else {
        // 拖拽结束：清除参考线
        clearGuides()
      }
      // 同步位置到 store
      store.updateNodePosition(change.id, change.position)
    }
    else if (change.type === 'remove') {
      // SLOT-04：删带附着子的父节点前弹确认（延后删）；无子节点直接删（零回归）。
      requestRemoveNode(change.id)
    }
  }
}

/**
 * 统一处理 VueFlow 内部边变更，回写到 Pinia store。
 * 只处理 remove（删除），其余忽略。
 */
function onEdgesChange(changes: EdgeChange[]) {
  for (const change of changes) {
    if (change.type === 'remove') {
      store.removeEdge(change.id)
    }
  }
}

function onNodeClick({ node }: NodeMouseEvent) {
  store.selectNode(node.id)
}

function onPaneClick() {
  store.selectNode(null)
}

// ============================================================================
// SLOT-03 磁吸交互：拖拽态驱动 + 吸附端点（snap-locked）+ 不兼容落点 Toast 拒绝
// ============================================================================

/** 拖拽连线吸附命中的目标端点（flow 坐标）；未命中为 null。透传给 CustomConnectionLine。 */
const snapTarget = ref<SnapTarget | null>(null)

/** 解析源 output 端口的契约 shape（用于 compatible-highlight / 吸附兼容判定数据源）。 */
function resolveSourceShape(nodeId: string, handleId: string): string | undefined {
  const node = store.nodes.find(n => n.id === nodeId)
  if (!node)
    return undefined
  return resolvePortShape(node.nodeType, handleId, 'output')
}

/**
 * 拖拽连线开始（VueFlow `@connect-start`）：解析源 handle shape 后驱动共享拖拽态。
 * 负载形如 `{ nodeId, handleId, handleType }`（handleType='source' 表示从 output 拉出）。
 */
function onConnectStart(payload: { nodeId?: string | null, handleId?: string | null, handleType?: string | null }) {
  const nodeId = payload?.nodeId
  const handleId = payload?.handleId
  if (!nodeId || !handleId)
    return
  startConnect(nodeId, handleId, resolveSourceShape(nodeId, handleId))
}

/** 拖拽连线结束（成功/取消统一）：复位拖拽态 + 清吸附端点。 */
function onConnectEnd() {
  endConnect()
  snapTarget.value = null
}

/**
 * 收集当前可见节点的 input handle 几何（flow 坐标）+ 兼容标注，作吸附候选。
 * 纯几何 O(n)：handle 取节点左缘，多入口在卡高度内均匀分布（happy-dom 无布局时尺寸为 0）。
 * 兼容性由 `isCompatibleTarget` 预标注——吸附只吸兼容候选（不放行不兼容，命门）。
 */
function collectSnapCandidates(): SnapCandidate[] {
  const result: SnapCandidate[] = []
  const srcId = connectSource.value?.nodeId
  for (const n of getNodes.value) {
    if (n.id === srcId)
      continue
    const nodeType = (n.data?.nodeType ?? n.type) as string | undefined
    if (!nodeType)
      continue
    const inputs = nodeTypesStore.getNodeType(nodeType)?.inputs ?? []
    if (!inputs.length)
      continue
    const fn = findNode(n.id)
    const pos = fn?.computedPosition ?? n.computedPosition ?? n.position ?? { x: 0, y: 0 }
    const dims = fn?.dimensions ?? { width: 0, height: 0 }
    inputs.forEach((port, i) => {
      result.push({
        nodeId: n.id,
        handleId: port.name,
        x: pos.x,
        y: pos.y + (dims.height * (i + 1)) / (inputs.length + 1),
        compatible: isCompatibleTarget(nodeType, port.name),
      })
    })
  }
  return result
}

/**
 * 高频拖拽指针：仅 dragging 时计算吸附端点（纯几何，不打日志）。
 * 屏幕坐标经 `screenToFlowCoordinate` 换算到 flow 后比距（阈值按 zoom 换算见 usePortSnap）。
 */
function updateSnapFromPointer(event: PointerEvent) {
  if (!connectDragging.value) {
    if (snapTarget.value)
      snapTarget.value = null
    return
  }
  const pointer = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  snapTarget.value = findSnapTarget(pointer, collectSnapCandidates(), vfViewport.value.zoom)
}

function onConnect(connection: Connection) {
  // 吸附命中时用吸附目标端口落点（吸附不绕合法性：落点仍走 getValidationError 双校验）。
  const snap = snapTarget.value
  const target = snap ? snap.nodeId : connection.target
  const targetHandle = snap ? snap.handleId : connection.targetHandle
  const effective: Connection = { ...connection, target, targetHandle }

  const validationError = getValidationError(effective, t)
  if (validationError) {
    showError(t('workflow.editor.slot.incompatibleTitle'), validationError)
    return
  }

  // SLOT-04 附着：方案节点 clarify 槽（shape=clarification_request）连澄清卡 →
  // store.attachChild 形成生命周期绑定编组，而非建普通边（UI-SPEC 方案 A）。
  const srcType = store.nodes.find(n => n.id === effective.source)?.nodeType
  const tgtType = store.nodes.find(n => n.id === target)?.nodeType
  const srcShape = srcType
    ? resolvePortShape(srcType, effective.sourceHandle ?? 'default', 'output')
    : undefined
  if (srcShape === 'clarification_request' && tgtType === 'clarification_card') {
    attachClarification(effective.source, target)
    return
  }

  store.addEdge({
    id: `edge-${effective.source}-${target}-${Date.now()}`,
    source: effective.source,
    target,
    sourcePort: effective.sourceHandle ?? 'default',
    targetPort: targetHandle ?? 'default',
    label: undefined,
    condition: null,
  })
}

// ============================================================================
// SLOT-04 附着编组：clarify 附着 + 琥珀虚线编组容器渲染 + 级联删除/解除确认
// ============================================================================

/** 父节点绝对位置 + 尺寸（findNode 几何优先；happy-dom 无布局时回退 store position/0 尺寸）。 */
function nodeBox(node: WorkflowNodeStore, parentAbs?: { x: number, y: number }) {
  const fn = findNode(node.id)
  const dims = fn?.dimensions ?? { width: 0, height: 0 }
  const cp = fn?.computedPosition
  let x: number
  let y: number
  if (cp) {
    x = cp.x
    y = cp.y
  }
  else {
    // 子节点 store position 为相对父，补父绝对换算为绝对；父节点直接用 own。
    const own = node.position ?? { x: 0, y: 0 }
    x = parentAbs ? parentAbs.x + own.x : own.x
    y = parentAbs ? parentAbs.y + own.y : own.y
  }
  return { x, y, w: dims.width, h: dims.height }
}

interface AttachGroup {
  parentId: string
  x: number
  y: number
  width: number
  height: number
  connectorX: number
  connectorY: number
}

/**
 * 附着编组容器（单一实现，WARNING 2 收敛）：对每个「有附着子」的父节点输出一个
 * `.slot-attach-group` 琥珀虚线容器（覆盖父子包围盒）+ 一个 `.slot-attach-connector`
 * 短实线琥珀连接器（父 clarify 槽右侧 → 子，≤24px）。派生 computed，不每帧建新对象遍历。
 */
const attachGroups = computed<AttachGroup[]>(() => {
  const childrenByParent = new Map<string, WorkflowNodeStore[]>()
  for (const n of storeNodes.value) {
    const pid = n.metadata?.parentNodeId
    if (typeof pid === 'string' && pid) {
      const arr = childrenByParent.get(pid) ?? []
      arr.push(n)
      childrenByParent.set(pid, arr)
    }
  }

  const groups: AttachGroup[] = []
  for (const [parentId, children] of childrenByParent) {
    const parent = storeNodes.value.find(n => n.id === parentId)
    if (!parent)
      continue
    const parentBox = nodeBox(parent)
    const parentAbs = { x: parentBox.x, y: parentBox.y }
    const boxes = [parentBox, ...children.map(c => nodeBox(c, parentAbs))]
    const minX = Math.min(...boxes.map(b => b.x))
    const minY = Math.min(...boxes.map(b => b.y))
    const maxX = Math.max(...boxes.map(b => b.x + b.w))
    const maxY = Math.max(...boxes.map(b => b.y + b.h))
    const pad = 8
    groups.push({
      parentId,
      x: minX - pad,
      y: minY - pad,
      width: maxX - minX + pad * 2,
      height: maxY - minY + pad * 2,
      // 连接器锚点：父卡右缘中点（短实线向子节点方向延伸）
      connectorX: parentBox.x + parentBox.w,
      connectorY: parentBox.y + parentBox.h / 2,
    })
  }
  return groups
})

/** 附着编组 overlay 随 viewport 平移/缩放（与 .vue-flow__viewport 同步）。 */
const overlayTransform = computed(() => {
  const { x, y, zoom } = vfViewport.value
  return { transform: `translate(${x}px, ${y}px) scale(${zoom})`, transformOrigin: '0 0' }
})

/**
 * 把澄清卡附着到方案节点：绝对→相对坐标换算（子相对父 = 子绝对 − 父绝对），
 * dock 到父卡 clarify 槽右下方（子在父左/上时给默认 dock 偏移）。
 */
function attachClarification(parentId: string, childId: string) {
  const parent = store.nodes.find(n => n.id === parentId)
  const child = store.nodes.find(n => n.id === childId)
  if (!parent || !child)
    return
  const parentBox = nodeBox(parent)
  const childBox = nodeBox(child)
  let relX = childBox.x - parentBox.x
  let relY = childBox.y - parentBox.y
  // dock 右下：子未在父右下方时给默认偏移（父宽 + 间距 / 父高 + 间距）
  if (relX < 20)
    relX = (parentBox.w || 240) + 48
  if (relY < 20)
    relY = (parentBox.h || 0) + 24
  store.attachChild(childId, parentId, { x: relX, y: relY })
}

// --- 级联删除确认（删带附着子的父节点前弹 deleteWithChildBody） ---
// WR-02：pendingDelete 持有**一批**带附着子的父节点 id（聚合确认），避免一次框选
// 含 ≥2 个带子父节点时单一 ref 互相覆盖致静默丢删。
const pendingDelete = ref<{ ids: string[], name: string, count: number } | null>(null)

/**
 * 删节点入口：无附着子 → 直接删（既有行为零回归）；有附着子 → 聚合进 pendingDelete
 * 延后确认。批量场景（handleBatchDelete / onNodesChange 多个 remove）多次调用本函数时，
 * 带子父节点逐个聚合（不再覆盖），确认后一并删除（WR-02）。
 */
function requestRemoveNode(id: string) {
  const count = store.getChildNodes(id).length
  if (count === 0) {
    store.removeNode(id)
    return
  }
  const prev = pendingDelete.value
  if (prev) {
    if (!prev.ids.includes(id)) {
      pendingDelete.value = {
        ids: [...prev.ids, id],
        name: prev.name,
        count: prev.count + count,
      }
    }
  }
  else {
    const node = store.nodes.find(n => n.id === id)
    pendingDelete.value = { ids: [id], name: node?.name ?? '', count }
  }
}

/** 级联删除确认弹窗正文：单个父节点带名展示；多个父节点聚合展示总数（WR-02）。 */
const deleteDialogBody = computed(() => {
  const p = pendingDelete.value
  if (!p)
    return ''
  if (p.ids.length > 1)
    return t('workflow.editor.slot.deleteWithChildBatchBody', { nodeCount: p.ids.length, count: p.count })
  return t('workflow.editor.slot.deleteWithChildBody', { name: p.name, count: p.count })
})

function confirmDelete() {
  if (pendingDelete.value) {
    // 逐个删除全部带子父节点（连同其附着子，store.removeNode 级联）。
    for (const id of pendingDelete.value.ids)
      store.removeNode(id)
  }
  pendingDelete.value = null
}

function cancelDelete() {
  pendingDelete.value = null
  // WR-03：取消后 store 未变，但 Vue Flow 可能已（经 applyDefault）移除被延后的父节点。
  // bump 版本号强制 vfNodes 产出新引用 → Vue Flow 从 store 重灌，恢复画布与 store 同步。
  canvasSyncVersion.value += 1
}

// --- 解除附着确认（子节点右键 → detachBody 确认 → 恢复独立绝对坐标） ---
const pendingDetach = ref<{ childId: string } | null>(null)

function onNodeContextMenu({ event, node }: NodeMouseEvent) {
  event?.preventDefault?.()
  const pid = (node?.data as { metadata?: { parentNodeId?: unknown } } | undefined)?.metadata?.parentNodeId
  if (typeof pid === 'string' && pid)
    pendingDetach.value = { childId: node.id }
}

function confirmDetach() {
  const childId = pendingDetach.value?.childId
  if (!childId) {
    pendingDetach.value = null
    return
  }
  const child = store.nodes.find(n => n.id === childId)
  const parentId = child?.metadata?.parentNodeId as string | undefined
  const parent = parentId ? store.nodes.find(n => n.id === parentId) : undefined
  // 相对→绝对：子绝对 = 父绝对 + 子相对（findNode 几何优先）
  const childAbs = findNode(childId)?.computedPosition
  const abs = childAbs
    ? { x: childAbs.x, y: childAbs.y }
    : {
        x: (parent?.position?.x ?? 0) + (child?.position?.x ?? 0),
        y: (parent?.position?.y ?? 0) + (child?.position?.y ?? 0),
      }
  store.detachChild(childId, abs)
  pendingDetach.value = null
}

function cancelDetach() {
  pendingDetach.value = null
}

function handleFitView() {
  fitView({ duration: 300 })
}

// 聚焦指定节点：选中 + 画布居中（仅 VueFlow 上下文内可调 fitView）。
// 通过共同祖先 provide 的持有器暴露给兄弟组件 IssuesPanel。
const workflowFocus = inject(WorkflowFocusKey, null)
function focusNode(nodeId: string) {
  store.selectNode(nodeId)
  fitView({ nodes: [nodeId], padding: 0.5, maxZoom: 1.2, duration: 400 })
}
if (workflowFocus)
  workflowFocus.focusNode = focusNode

// 一键自动布局：横向 LR 重排（写回 store + 单步历史）后 fitView 居中。
function runAutoLayout() {
  const has = applyAutoLayout()
  if (has)
    fitView({ duration: 300 })
}
if (workflowFocus)
  workflowFocus.autoLayout = runAutoLayout

onBeforeUnmount(() => {
  if (workflowFocus) {
    workflowFocus.focusNode = null
    workflowFocus.autoLayout = null
  }
})

// MiniMap 双击检测：MiniMap 内部 pannable 事件会吞掉 dblclick，
// 因此在 capture 阶段手动检测连续两次 click 的间隔 (< 300ms)
let lastMiniMapClick = 0
function handleMiniMapClickCapture(event: MouseEvent) {
  const now = Date.now()
  if (now - lastMiniMapClick < 300) {
    handleFitView()
    lastMiniMapClick = 0
  }
  else {
    lastMiniMapClick = now
  }
}

function handleBatchDelete() {
  const selectedIds = getSelectedNodes.value.map(n => n.id)
  // 经 requestRemoveNode：无附着子直接删；带子的弹级联删除确认。
  selectedIds.forEach(id => requestRemoveNode(id))
}

function handleBatchCopy() {
  const selected = getSelectedNodes.value
  selected.forEach((node) => {
    const storeNode = store.nodes.find(n => n.id === node.id)
    if (!storeNode)
      return
    const newNode = {
      ...JSON.parse(JSON.stringify(storeNode)),
      id: randomUUID(),
      shortId: generateShortId(),
      position: {
        x: (storeNode.position?.x ?? 0) + 50,
        y: (storeNode.position?.y ?? 0) + 50,
      },
    }
    newNode.name = `${storeNode.name} (副本)`
    store.addNode(newNode)
  })
}

// 暴露内部处理器供单测驱动（无真实 @vue-flow 画布交互时的可测面）。
defineExpose({
  vfNodes,
  vfEdges,
  signalLayerEnabled,
  toggleSignalLayer,
  signalEdges,
  signalTargetNodes,
  onConnectStart,
  onConnectEnd,
  onConnect,
  updateSnapFromPointer,
  collectSnapCandidates,
  snapTarget,
  attachGroups,
  requestRemoveNode,
  handleBatchDelete,
  confirmDelete,
  cancelDelete,
  pendingDelete,
  deleteDialogBody,
  onNodeContextMenu,
  confirmDetach,
  cancelDetach,
  pendingDetach,
})
</script>

<template>
  <div class="h-full w-full bg-background">
    <VueFlow
      :nodes="vfNodes"
      :edges="vfEdges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :is-valid-connection="validateConnection"
      :connection-mode="ConnectionMode.Strict"
      :snap-to-grid="true"
      :snap-grid="[15, 15]"
      :max-zoom="1.5"
      :min-zoom="0.2"
      multi-selection-key-code="Shift"
      :selection-mode="SelectionMode.Partial"
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
      @node-drag-start="onNodeDragStart"
      @node-drag-stop="onNodeDragStop"
      @node-click="onNodeClick"
      @pane-click="onPaneClick"
      @node-context-menu="onNodeContextMenu"
      @connect-start="onConnectStart"
      @connect-end="onConnectEnd"
      @connect="onConnect"
      @dragover="onDragOver"
      @drop="onDrop"
      @pointermove="updateSnapFromPointer"
    >
      <!-- 拖拽连线：与连成后的边同参数（单一 bezier）；命中吸附时透传 snap 端点（snap-locked） -->
      <template #connection-line="connectionLineProps">
        <CustomConnectionLine
          v-bind="connectionLineProps"
          :snap-x="snapTarget?.x"
          :snap-y="snapTarget?.y"
        />
      </template>

      <!-- SLOT-04 附着编组容器（单一实现）：随 viewport 平移/缩放，沉于节点之下 -->
      <div
        class="slot-attach-overlay pointer-events-none absolute inset-0 z-0 overflow-visible"
        :style="overlayTransform"
      >
        <div
          v-for="group in attachGroups"
          :key="group.parentId"
          class="slot-attach-group absolute bg-amber-500/[0.04] border border-dashed border-amber-400/40 rounded-2xl"
          :style="{
            left: `${group.x}px`,
            top: `${group.y}px`,
            width: `${group.width}px`,
            height: `${group.height}px`,
          }"
        >
          <!-- 短实线琥珀连接器（父 clarify 槽 → 子，长度 24px） -->
          <div
            class="slot-attach-connector absolute bg-amber-400/70 rounded-full"
            :style="{
              left: `${group.connectorX - group.x}px`,
              top: `${group.connectorY - group.y}px`,
              width: '24px',
              height: '2px',
            }"
          />
        </div>
      </div>

      <!-- P6 信号层开关：切换「只看交付流 / 叠加信号订阅层」 -->
      <Panel position="top-left">
        <div class="flex flex-col gap-1.5">
          <button
            class="signal-layer-toggle flex items-center gap-1.5 bg-card/90 backdrop-blur-sm border rounded-xl px-3 py-1.5 shadow-lg text-xs font-medium transition-colors"
            :class="signalLayerEnabled
              ? 'border-primary/50 text-primary'
              : 'border-border/50 text-muted-foreground hover:text-foreground'"
            :title="signalLayerEnabled
              ? '当前：叠加信号层。点击切回只看交付流'
              : '当前：只看交付流。点击叠加信号订阅层（虚线显示通知/文档订阅的宿主信号）'"
            @click="toggleSignalLayer"
          >
            <Waypoints class="w-3.5 h-3.5" />
            <span>{{ signalLayerEnabled ? '信号层 · 开' : '信号层' }}</span>
          </button>
          <!-- 信号语义色图例（仅信号层开启时显示） -->
          <div
            v-if="signalLayerEnabled"
            class="flex items-center gap-2.5 bg-card/90 backdrop-blur-sm border border-border/50 rounded-xl px-3 py-1.5 shadow-lg text-[10px] text-muted-foreground"
          >
            <span class="flex items-center gap-1">
              <span class="inline-block w-3 border-t border-dashed" style="border-color: #10b981;" />成功
            </span>
            <span class="flex items-center gap-1">
              <span class="inline-block w-3 border-t border-dashed" style="border-color: #ef4444;" />失败
            </span>
            <span class="flex items-center gap-1">
              <span class="inline-block w-3 border-t border-dashed" style="border-color: #8b5cf6;" />产出
            </span>
          </div>
        </div>
      </Panel>

      <Background
        variant="dots"
        :gap="35"
        :size="1.5"
        color="#14b8a626"
      />
      <!-- @click.capture 在捕获阶段检测双击 — MiniMap 内部 pannable 会吞掉 dblclick -->
      <Panel position="bottom-right" @click.capture="handleMiniMapClickCapture">
        <MiniMap
          :pannable="true"
          :zoomable="true"
          mask-color="rgba(0, 0, 0, 0.08)"
          class="!bg-card/80 !backdrop-blur-sm !border !border-border/50 !rounded-2xl !shadow-lg"
        />
      </Panel>
      <Controls
        position="bottom-left"
        :show-zoom="true"
        :show-fit-view="true"
        :show-interactive="false"
        class="!bg-card/80 !backdrop-blur-sm !border !border-border/50 !rounded-2xl !shadow-lg"
      />
      <!-- 对齐辅助线 overlay：仅拖拽节点时渲染，松手即隐藏（修复虚线常驻） -->
      <svg
        v-if="isDragging"
        class="pointer-events-none absolute inset-0 z-[1000] overflow-visible"
        style="width: 100%; height: 100%;"
      >
        <line
          v-for="(line, index) in guideLines"
          :key="index"
          :x1="line.x1"
          :y1="line.y1"
          :x2="line.x2"
          :y2="line.y2"
          stroke="#14b8a6"
          stroke-width="1"
          stroke-dasharray="4 4"
          opacity="0.7"
        />
      </svg>

      <!-- 多选统一工具栏 -->
      <Panel v-if="multiSelectCount > 1" position="top-center">
        <div class="flex items-center gap-2 bg-card/90 backdrop-blur-sm border border-border/50 rounded-xl px-3 py-1.5 shadow-lg">
          <span class="text-xs text-muted-foreground">已选 {{ multiSelectCount }} 个节点</span>
          <div class="w-px h-4 bg-border/50" />
          <button
            class="p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            title="复制选中节点"
            @click="handleBatchCopy"
          >
            <Copy class="w-3.5 h-3.5" />
          </button>
          <button
            class="p-1.5 rounded-lg hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
            title="删除选中节点"
            @click="handleBatchDelete"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>
      </Panel>
    </VueFlow>

    <!-- SLOT-04 级联删除确认：删带附着子的方案节点前确认（一并移除附着澄清节点） -->
    <AlertDialog :open="!!pendingDelete" @update:open="(open) => { if (!open) cancelDelete() }">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t('workflow.editor.slot.deleteTitle') }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{ deleteDialogBody }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cancelDelete">
            {{ t('workflow.editor.slot.cancel') }}
          </AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-destructive-foreground hover:bg-destructive/90" @click="confirmDelete">
            {{ t('workflow.editor.slot.delete') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <!-- SLOT-04 解除附着确认：澄清子节点恢复独立坐标，不再随方案节点联动 -->
    <AlertDialog :open="!!pendingDetach" @update:open="(open) => { if (!open) cancelDetach() }">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t('workflow.editor.slot.detachTitle') }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{ t('workflow.editor.slot.detachBody') }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="cancelDetach">
            {{ t('workflow.editor.slot.cancel') }}
          </AlertDialogCancel>
          <AlertDialogAction @click="confirmDetach">
            {{ t('workflow.editor.slot.detachTitle') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>

<style>
/* P6 信号层 surfaced 目标节点：弱化呈现，与实线交付层节点视觉区分（虚线订阅边的落点）。 */
.signal-surfaced-node {
  opacity: 0.78;
  filter: saturate(0.85);
}
</style>
