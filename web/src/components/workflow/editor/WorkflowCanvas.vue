<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * 数据同步策略：Pinia store 是 source of truth，通过 :nodes/:edges 单向传入 VueFlow。
 * VueFlow 的所有内部变更（拖拽、删除等）通过 @nodes-change/@edges-change 统一回写 store。
 */
import type { Connection, EdgeChange, NodeChange, NodeMouseEvent } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { Panel, SelectionMode, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { Copy, Trash2 } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, inject, markRaw, onBeforeUnmount } from 'vue'
import { WorkflowFocusKey } from '~/components/workflow/workflowFocus'
import { useToast } from '~/composables/useToast'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'
import { useAlignmentGuides } from './composables/useAlignmentGuides'
import { useAutoLayout } from './composables/useAutoLayout'
import { getValidationError, useConnectionValidator } from './composables/useConnectionValidator'
import { useDragAndDrop } from './composables/useDragAndDrop'
import { useKeyboardShortcuts } from './composables/useKeyboardShortcuts'
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

const { error: showError } = useToast()
const { getSelectedNodes, fitView, viewport: vfViewport } = useVueFlow()
const { validateConnection } = useConnectionValidator()
const { applyAutoLayout } = useAutoLayout()
const { onDragOver, onDrop } = useDragAndDrop()
const { alignmentGuides, checkAlignment, clearGuides } = useAlignmentGuides()
useKeyboardShortcuts()

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

function onConnect(connection: Connection) {
  const validationError = getValidationError(connection)
  if (validationError) {
    showError('连线失败', validationError)
    return
  }
  store.addEdge({
    id: `edge-${connection.source}-${connection.target}-${Date.now()}`,
    source: connection.source,
    target: connection.target,
    sourcePort: connection.sourceHandle ?? 'default',
    targetPort: connection.targetHandle ?? 'default',
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
</script>

<template>
  <div class="h-full w-full bg-background">
    <VueFlow
      :nodes="vfNodes"
      :edges="vfEdges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :is-valid-connection="validateConnection"
      :snap-to-grid="true"
      :snap-grid="[15, 15]"
      :max-zoom="1.5"
      :min-zoom="0.2"
      multi-selection-key-code="Shift"
      :selection-mode="SelectionMode.Partial"
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
      @node-click="onNodeClick"
      @pane-click="onPaneClick"
      @connect="onConnect"
      @dragover="onDragOver"
      @drop="onDrop"
    >
      <!-- 拖拽连线：与连成后的边同参数（单一 bezier，source=Right→target=Left） -->
      <template #connection-line="connectionLineProps">
        <CustomConnectionLine v-bind="connectionLineProps" />
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
      <!-- 对齐辅助线 overlay -->
      <svg
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
