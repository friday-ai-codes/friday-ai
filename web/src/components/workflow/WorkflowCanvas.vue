<script setup lang="ts">
import type { Connection, Edge, Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MarkerType, Position, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted, ref } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
// Custom Nodes
import ActionNode from './nodes/ActionNode.vue'
import ApprovalNode from './nodes/ApprovalNode.vue'
import ControlNode from './nodes/ControlNode.vue'
import TriggerNode from './nodes/TriggerNode.vue'
// Props
defineProps<{
 editable?: boolean
}>
// Stores
const store = useWorkflowsStore
const nodeTypesStore = useNodeTypesStore
const { nodes, edges } = storeToRefs(store)
// Drag state
const isDragOver = ref(false)
const vueFlowRef = ref<InstanceType<typeof VueFlow> | null>(null)
// Node Types Registration
const nodeTypes = {
 // Triggers
 manual_trigger: markRaw(TriggerNode),
 webhook_trigger: markRaw(TriggerNode),
 schedule_trigger: markRaw(TriggerNode),
 // Actions
 http_request: markRaw(ActionNode),
 code_implement: markRaw(ActionNode),
 create_branch: markRaw(ActionNode),
 // Approval
 human_approval: markRaw(ApprovalNode),
 approval: markRaw(ApprovalNode),
 // Control
 condition: markRaw(ControlNode),
 delay: markRaw(ControlNode),
 parallel: markRaw(ControlNode),
}
// 默认边样式
const defaultEdgeOptions = {
 type: 'smoothstep',
 animated: true,
 style: { strokeWidth: 2 },
 markerEnd: MarkerType.ArrowClosed,
}
// Connection handler - 当连接完成时添加边
function handleConnect(connection: Connection) {
 if (!connection.source || !connection.target) return
 const newEdge: Edge = {
 id: `e-${connection.source}-${connection.target}-${Date.now}`,
 source: connection.source,
 target: connection.target,
 sourceHandle: connection.sourceHandle || 'source',
 targetHandle: connection.targetHandle || 'target',
 type: 'smoothstep',
 animated: true,
 markerEnd: MarkerType.ArrowClosed,
 }
 store.addEdge(newEdge)
}
// Node drag stop handler
function handleNodeDragStop(event: { node: Node }) {
 store.updateNode(event.node.id, { position: event.node.position })
}
// Node click handler
function handleNodeClick(event: { node: Node }) {
 store.selectNode(event.node.id)
}
// Pane click handler
function handlePaneClick {
 store.selectNode(null)
}
// Drag and Drop handlers
function onDragOver(event: DragEvent) {
 event.preventDefault
 if (event.dataTransfer) {
 event.dataTransfer.dropEffect = 'move'
 }
 isDragOver.value = true
}
function onDragLeave(event: DragEvent) {
 // 只有当离开整个容器时才设置为 false
 const rect = (event.currentTarget as HTMLElement).getBoundingClientRect
 if (
 event.clientX < rect.left ||
 event.clientX > rect.right ||
 event.clientY < rect.top ||
 event.clientY > rect.bottom
 ) {
 isDragOver.value = false
 }
}
function onDrop(event: DragEvent) {
 event.preventDefault
 isDragOver.value = false
 const type = event.dataTransfer?.getData('application/vueflow')
 if (!type) return
 // 获取画布容器的位置
 const flowContainer = event.currentTarget as HTMLElement
 const bounds = flowContainer.getBoundingClientRect
 // 计算相对于画布的位置
 const position = {
 x: event.clientX - bounds.left - 100, // 居中偏移
 y: event.clientY - bounds.top - 40,
 }
 const nodeTypeInfo = nodeTypesStore.getNodeType(type)
 const displayName = nodeTypeInfo?.display_name || type.replace(/_/g, ' ')
 const newNode: Node = {
 id: crypto.randomUUID,
 type,
 position,
 label: displayName,
 data: {
 node_type: type,
 name: displayName,
 config: {},
 description: nodeTypeInfo?.description || '',
 },
 }
 store.addNode(newNode)
}
// Load node types on mount
onMounted( => {
 nodeTypesStore.fetchNodeTypes
})
</script>
<template>
 <div
 class="h-full w-full workflow-canvas":class="{ 'drag-over': isDragOver }"
 @drop="onDrop"
 @dragover="onDragOver"
 @dragleave="onDragLeave"
 >
 <VueFlow
 ref="vueFlowRef"
 v-model:nodes="nodes"
 v-model:edges="edges":node-types="nodeTypes":default-edge-options="defaultEdgeOptions":default-viewport="{ zoom: 1, x: 50, y: 50 }":min-zoom="0.2":max-zoom="4":nodes-draggable="editable":nodes-connectable="editable":elements-selectable="true":snap-to-grid="true":snap-grid="[20, 20]":connect-on-click="false":fit-view-on-init="false":pan-on-drag="true":zoom-on-scroll="true"
 class="vue-flow-wrapper"
 @connect="handleConnect"
 @node-drag-stop="handleNodeDragStop"
 @node-click="handleNodeClick"
 @pane-click="handlePaneClick"
 >
 <!-- 背景网格 -->
 <Background:variant="'dots'":gap="20":size="1"
 pattern-color="hsl(219 30% 65% / 0.4)"
 />
 <!-- 小地图 -->
 <MiniMap:pannable="true":zoomable="true"
 class="vue-flow-minimap"
 />
 <!-- 控制按钮 -->
 <Controls:show-interactive="false" />
 </VueFlow>
 <!-- Drop indicator overlay -->
 <div
 v-if="isDragOver"
 class="absolute inset-0 pointer-events-none flex items-center justify-center bg-primary/5 border-2 border-dashed border-primary/30 rounded-lg z-10"
 >
 <div class="text-primary font-medium bg-background/90 px-4 py-2 rounded-md shadow-sm">
 释放以添加节点
 </div>
 </div>
 </div>
</template>
<style>
/* Vue Flow 必要样式 */
@import '@vue-flow/core/dist/style.css';
@import '@vue-flow/core/dist/theme-default.css';
@import '@vue-flow/controls/dist/style.css';
@import '@vue-flow/minimap/dist/style.css';
.workflow-canvas {
 position: relative;
 background: #f8fafc;
}
.workflow-canvas.drag-over {
 background: #eff6ff;
}
.vue-flow-wrapper {
 width: 100%;
 height: 100%;
}
/* Node 选中状态 */
.vue-flow .vue-flow__node.selected {
 outline: none;
}
</style>
