<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * 数据同步策略：Pinia store 是 source of truth，通过 :nodes/:edges 单向传入 VueFlow。
 * VueFlow 的所有内部变更（拖拽、删除等）通过 @nodes-change/@edges-change 统一回写 store。
 */
import type { Connection, EdgeChange, NodeChange, NodeMouseEvent } from '@vue-flow/core'
import type { SnapCandidate, SnapTarget } from './composables/usePortSnap'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { ConnectionMode, Panel, SelectionMode, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { Copy, Trash2 } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, inject, markRaw, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
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
import { toVueFlowEdges, toVueFlowNodes } from './composables/useWorkflowTransform'
import CustomConnectionLine from './edges/CustomConnectionLine.vue'
import GradientEdge from './edges/GradientEdge.vue'
import { nodeTypes } from './nodes'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'

const store = useWorkflowsStore()
const { nodes: storeNodes, edges: storeEdges } = storeToRefs(store)

const vfNodes = computed(() => toVueFlowNodes(storeNodes.value))
const vfEdges = computed(() => toVueFlowEdges(storeEdges.value, storeNodes.value))

const edgeTypes = { gradient: markRaw(GradientEdge) }

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
      store.removeNode(change.id)
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
  selectedIds.forEach(id => store.removeNode(id))
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
  onConnectStart,
  onConnectEnd,
  onConnect,
  updateSnapFromPointer,
  collectSnapCandidates,
  snapTarget,
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
  </div>
</template>
