<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * 数据同步策略：Pinia store 是 source of truth，通过:nodes/:edges 单向传入 VueFlow。
 * VueFlow 的所有内部变更（拖拽、删除等）通过 @nodes-change/@edges-change 统一回写 store。
 */
import type { Connection, EdgeChange, NodeChange, NodeMouseEvent } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { Panel, SelectionMode, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { Copy, Trash2 } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, markRaw } from 'vue'
import { useToast } from '~/composables/useToast'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { generateShortId } from '~/utils/shortId'
import { getValidationError, useConnectionValidator } from './composables/useConnectionValidator'
import { useDragAndDrop } from './composables/useDragAndDrop'
import { useKeyboardShortcuts } from './composables/useKeyboardShortcuts'
import { toVueFlowEdges, toVueFlowNodes } from './composables/useWorkflowTransform'
import GradientEdge from './edges/GradientEdge.vue'
import { nodeTypes } from './nodes'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'
const store = useWorkflowsStore
const { nodes: storeNodes, edges: storeEdges } = storeToRefs(store)
const vfNodes = computed( => toVueFlowNodes(storeNodes.value))
const vfEdges = computed( => toVueFlowEdges(storeEdges.value))
const edgeTypes = { gradient: markRaw(GradientEdge) }
const { error: showError } = useToast
const { getSelectedNodes, fitView } = useVueFlow
const { validateConnection } = useConnectionValidator
const { onDragOver, onDrop } = useDragAndDrop
useKeyboardShortcuts
/** 多选节点数量 */
const multiSelectCount = computed( => getSelectedNodes.value.length)
/**
 * 统一处理 VueFlow 内部节点变更，回写到 Pinia store。
 * 只处理 position（拖拽结束）和 remove（删除），其余忽略。
 */
function onNodesChange(changes: NodeChange) {
 for (const change of changes) {
 if (change.type === 'position' && change.position) {
 // 拖拽中和拖拽结束都同步位置到 store，
 // 避免其他操作触发 vfNodes 重新计算时用旧位置覆盖
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
function onEdgesChange(changes: EdgeChange) {
 for (const change of changes) {
 if (change.type === 'remove') {
 store.removeEdge(change.id)
 }
 }
}
function onNodeClick({ node }: NodeMouseEvent) {
 store.selectNode(node.id)
}
function onPaneClick {
 store.selectNode(null)
}
function onConnect(connection: Connection) {
 const validationError = getValidationError(connection)
 if (validationError) {
 showError('连线失败', validationError)
 return
 }
 store.addEdge({
 id: `edge-${connection.source}-${connection.target}-${Date.now}`,
 source: connection.source,
 target: connection.target,
 sourcePort: connection.sourceHandle ?? 'default',
 targetPort: connection.targetHandle ?? 'default',
 label: undefined,
 condition: null,
 })
}
function handleFitView {
 fitView({ duration: 300 })
}
function handleBatchDelete {
 const selectedIds = getSelectedNodes.value.map(n => n.id)
 selectedIds.forEach(id => store.removeNode(id))
}
function handleBatchCopy {
 const selected = getSelectedNodes.value
 selected.forEach((node) => {
 const storeNode = store.nodes.find(n => n.id === node.id)
 if (!storeNode)
 return
 const newNode = {
 ...JSON.parse(JSON.stringify(storeNode)),
 id: crypto.randomUUID,
 shortId: generateShortId,
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
 <VueFlow:nodes="vfNodes":edges="vfEdges":node-types="nodeTypes":edge-types="edgeTypes":is-valid-connection="validateConnection":snap-to-grid="true":snap-grid="[15, 15]":max-zoom="1.5":min-zoom="0.2"
 multi-selection-key-code="Shift":selection-mode="SelectionMode.Partial"
 @nodes-change="onNodesChange"
 @edges-change="onEdgesChange"
 @node-click="onNodeClick"
 @pane-click="onPaneClick"
 @connect="onConnect"
 @dragover="onDragOver"
 @drop="onDrop"
 >
 <Background
 variant="dots":gap="35":size="1.5"
 color="#3b82f620"
 />
 <!-- Wrapper 用于捕获 dblclick — MiniMap 内部 pannable 事件会吞掉原生 dblclick -->
 <Panel position="bottom-right">
 <div @dblclick="handleFitView">
 <MiniMap:pannable="true":zoomable="true"
 mask-color="rgba(0, 0, 0, 0.08)"
 class="!bg-card/80 !backdrop-blur-sm !border !border-border/50 !rounded-2xl !shadow-lg"
 />
 </div>
 </Panel>
 <Controls
 position="bottom-left":show-zoom="true":show-fit-view="true":show-interactive="false"
 class="!bg-card/80 !backdrop-blur-sm !border !border-border/50 !rounded-2xl !shadow-lg"
 />
 <!-- 多选统一工具栏 -->
 <Panel v-if="multiSelectCount > 1" position="top-center">
 <div class="flex items-center gap-2 bg-card/90 backdrop-blur-sm border border-border/50 rounded-xl px-3 py-1.5 shadow-lg">
 <span class="text-xs text-muted-foreground">已选 {{ multiSelectCount }} 个节点</span>
 <div class="w-px bg-border/50" />
 <button
 class=".5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
 title="复制选中节点"
 @click="handleBatchCopy"
 >
 <Copy class="w-3.5 .5" />
 </button>
 <button
 class=".5 rounded-lg hover:bg-destructive/10 transition-colors text-muted-foreground hover:text-destructive"
 title="删除选中节点"
 @click="handleBatchDelete"
 >
 <Trash2 class="w-3.5 .5" />
 </button>
 </div>
 </Panel>
 </VueFlow>
 </div>
</template>
