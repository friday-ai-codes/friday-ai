<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * Phase: basic canvas + dot background + store sync.
 * Phase: connection validation, gradient edges, sidebar drag-and-drop.
 * Phase: MiniMap, Controls plugins + node-click/pane-click event wiring.
 */
import type { NodeDragEvent, NodeMouseEvent, Connection } from '@vue-flow/core'
import { Panel, VueFlow, SelectionMode, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'
import { Copy, Trash2 } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, markRaw } from 'vue'
import { toast } from 'vue-sonner'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { generateShortId } from '~/utils/shortId'
import { toVueFlowNodes, toVueFlowEdges } from './composables/useWorkflowTransform'
import { useConnectionValidator, getValidationError } from './composables/useConnectionValidator'
import { useDragAndDrop } from './composables/useDragAndDrop'
import { useKeyboardShortcuts } from './composables/useKeyboardShortcuts'
import { nodeTypes } from './nodes'
import GradientEdge from './edges/GradientEdge.vue'
const store = useWorkflowsStore
const { nodes: storeNodes, edges: storeEdges } = storeToRefs(store)
const vfNodes = computed( => toVueFlowNodes(storeNodes.value))
const vfEdges = computed( => toVueFlowEdges(storeEdges.value))
const edgeTypes = { gradient: markRaw(GradientEdge) }
const { getSelectedNodes } = useVueFlow
const { validateConnection } = useConnectionValidator
const { onDragOver, onDrop } = useDragAndDrop
useKeyboardShortcuts
/** 多选节点数量 */
const multiSelectCount = computed( => getSelectedNodes.value.length)
function onNodeDragStop(event: NodeDragEvent) {
 for (const node of event.nodes) {
 store.updateNodePosition(node.id, node.position)
 }
}
function onNodeClick({ node }: NodeMouseEvent) {
 store.selectNode(node.id)
}
function onPaneClick {
 store.selectNode(null)
}
function onConnect(connection: Connection) {
 const error = getValidationError(connection)
 if (error) {
 toast.error('连线失败', { description: error })
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
function handleBatchDelete {
 const selectedIds = getSelectedNodes.value.map(n => n.id)
 selectedIds.forEach(id => store.removeNode(id))
}
function handleBatchCopy {
 const selected = getSelectedNodes.value
 selected.forEach(node => {
 const storeNode = store.nodes.find(n => n.id === node.id)
 if (!storeNode) return
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
 <VueFlow:nodes="vfNodes":edges="vfEdges":node-types="nodeTypes":edge-types="edgeTypes":is-valid-connection="validateConnection":max-zoom="1.5":min-zoom="0.2"
 multi-selection-key-code="Shift":selection-mode="SelectionMode.Partial"
 @node-drag-stop="onNodeDragStop"
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
 <MiniMap
 position="bottom-right":pannable="true":zoomable="true":mask-color="'rgba(0, 0, 0, 0.08)'"
 class="!bg-card/80 !backdrop-blur-sm !border !border-border/50 !rounded-2xl !shadow-lg"
 />
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
