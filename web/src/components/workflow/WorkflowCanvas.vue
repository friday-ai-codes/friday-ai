<script setup lang="ts">
import type { Connection, Edge, Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MarkerType, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted, ref, watch } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { useDragPreview } from './composables/useDragPreview'
import { useNodeCollision } from './composables/useNodeCollision'
// Custom Edges
import { GradientEdge } from './edges'
// Custom Nodes
import ActionNode from './nodes/ActionNode.vue'
import AICodingDispatcherNode from './nodes/AICodingDispatcherNode.vue'
import AIPromptNode from './nodes/AIPromptNode.vue'
import AIVariableExtractorNode from './nodes/AIVariableExtractorNode.vue'
import ApprovalNode from './nodes/ApprovalNode.vue'
import ContextRetrievalNode from './nodes/ContextRetrievalNode.vue'
import ControlNode from './nodes/ControlNode.vue'
import FeishuEventTriggerNode from './nodes/FeishuEventTriggerNode.vue'
import FetchProjectInfoNode from './nodes/FetchProjectInfoNode.vue'
import FetchWorkItemNode from './nodes/FetchWorkItemNode.vue'
import TechnicalPlanNode from './nodes/TechnicalPlanNode.vue'
import TriggerNode from './nodes/TriggerNode.vue'
import VariableExtractorNode from './nodes/VariableExtractorNode.vue'
import WaitFeishuNode from './nodes/WaitFeishuNode.vue'
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
// 使用 useVueFlow 获取 project 方法和节点更新方法
const { project, updateNode: vueFlowUpdateNode } = useVueFlow
// Drag preview state
const {
 isDragging: isNodeDragging,
 previewPosition,
 onDragStart,
 onDrag,
 onDragStop,
} = useDragPreview(20)
// Collision detection state
const {
 collisionWarningNodeId,
 isColliding,
 findValidPosition,
 checkAndConstrainPosition,
 initDragPosition,
 clearWarning,
} = useNodeCollision( => nodes.value)
// Node Types Registration
const nodeTypes = {
 // Triggers
 manual_trigger: markRaw(TriggerNode),
 webhook_trigger: markRaw(TriggerNode),
 schedule_trigger: markRaw(TriggerNode),
 feishu_event_trigger: markRaw(FeishuEventTriggerNode),
 // Actions
 http_request: markRaw(ActionNode),
 code_implement: markRaw(ActionNode),
 create_branch: markRaw(ActionNode),
 // Integration
 fetch_work_item: markRaw(FetchWorkItemNode),
 fetch_project_info: markRaw(FetchProjectInfoNode),
 // Data Processing
 variable_extractor: markRaw(VariableExtractorNode),
 // AI
 ai_prompt: markRaw(AIPromptNode),
 ai_coding_dispatcher: markRaw(AICodingDispatcherNode),
 ai_variable_extractor: markRaw(AIVariableExtractorNode),
 context_retrieval: markRaw(ContextRetrievalNode),
 ai_technical_plan: markRaw(TechnicalPlanNode),
 // Approval
 human_approval: markRaw(ApprovalNode),
 approval: markRaw(ApprovalNode),
 // Control
 condition: markRaw(ControlNode),
 delay: markRaw(ControlNode),
 parallel: markRaw(ControlNode),
 wait_feishu_field: markRaw(WaitFeishuNode),
}
// Edge Types Registration
const edgeTypes = {
 gradient: markRaw(GradientEdge),
}
// Node type to color mapping for gradient edges
const nodeTypeColorMap: Record<string, string> = {
 // Triggers - blue
 manual_trigger: '#3b82f6',
 webhook_trigger: '#3b82f6',
 schedule_trigger: '#3b82f6',
 feishu_event_trigger: '#3b82f6',
 // AI nodes - purple
 ai_prompt: '#8b5cf6',
 ai_coding_dispatcher: '#8b5cf6',
 ai_variable_extractor: '#8b5cf6',
 context_retrieval: '#8b5cf6',
 ai_technical_plan: '#8b5cf6',
 // Integration - orange
 fetch_work_item: '#f59e0b',
 fetch_project_info: '#f59e0b',
 // Data/Control - cyan
 variable_extractor: '#06b6d4',
 condition: '#06b6d4',
 wait_feishu_field: '#06b6d4',
 delay: '#06b6d4',
 parallel: '#06b6d4',
 // Actions - green
 http_request: '#10b981',
 create_branch: '#10b981',
 code_implement: '#10b981',
 approval: '#10b981',
 human_approval: '#10b981',
}
/**
 * Get color for a node type
 */
function getNodeTypeColor(nodeType: string): string {
 return nodeTypeColorMap[nodeType] || '#6366f1' // indigo as fallback
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
 if (!connection.source || !connection.target)
 return
 // Find source and target nodes to get their types for gradient colors
 const sourceNode = nodes.value.find(n => n.id === connection.source)
 const targetNode = nodes.value.find(n => n.id === connection.target)
 const sourceNodeType = sourceNode?.type || sourceNode?.data?.node_type || ''
 const targetNodeType = targetNode?.type || targetNode?.data?.node_type || ''
 // Use gradient edge type with color data for all new connections
 const newEdge: Edge = {
 id: `e-${connection.source}-${connection.target}-${Date.now}`,
 source: connection.source,
 target: connection.target,
 sourceHandle: connection.sourceHandle || 'source',
 targetHandle: connection.targetHandle || 'target',
 type: 'gradient',
 animated: false,
 data: {
 sourceColor: getNodeTypeColor(sourceNodeType),
 targetColor: getNodeTypeColor(targetNodeType),
 sourceNodeType,
 targetNodeType,
 },
 }
 store.addEdge(newEdge)
}
// Node drag start handler
function handleNodeDragStart(event: { node: Node }) {
 onDragStart(event.node)
 // Initialize collision tracking with current position
 initDragPosition(event.node.position)
}
// Node drag handler - constrain position to prevent overlap
function handleNodeDrag(event: { node: Node }) {
 onDrag(event.node)
 // Check collision and constrain position during drag
 const nodeWithDims = event.node as Node & { dimensions?: { width: number; height: number } }
 const result = checkAndConstrainPosition(
 event.node.id,
 event.node.position,
 nodeWithDims.dimensions
 )
 // If colliding, force node back to last valid position using Vue Flow's internal updateNode
 if (result.collides && result.position) {
 // Use Vue Flow's updateNode directly to override the drag position
 vueFlowUpdateNode(event.node.id, { position: result.position })
 // Also sync to store
 store.updateNode(event.node.id, { position: result.position })
 }
}
// Node drag stop handler
function handleNodeDragStop(event: { node: Node }) {
 const snappedPosition = onDragStop
 const targetPosition = snappedPosition || event.node.position
 // Find valid position if current position collides
 const nodeWithDims = event.node as Node & { dimensions?: { width: number; height: number } }
 const validPosition = findValidPosition(
 targetPosition,
 event.node.id,
 nodeWithDims.dimensions
 )
 store.updateNode(event.node.id, { position: validPosition })
 clearWarning
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
 event.clientX < rect.left
 || event.clientX > rect.right
 || event.clientY < rect.top
 || event.clientY > rect.bottom
 ) {
 isDragOver.value = false
 }
}
function onDrop(event: DragEvent) {
 event.preventDefault
 isDragOver.value = false
 const type = event.dataTransfer?.getData('application/vueflow')
 if (!type)
 return
 // 获取画布容器的位置
 const flowContainer = event.currentTarget as HTMLElement
 const bounds = flowContainer.getBoundingClientRect
 // 使用 project 方法将屏幕坐标转换为画布坐标
 const position = project({
 x: event.clientX - bounds.left,
 y: event.clientY - bounds.top,
 })
 // 居中偏移（节点宽度约 200px，高度约 80px）
 position.x -= 100
 position.y -= 40
 // Find valid position if dropping would cause collision
 const tempNodeId = 'temp-drop-check'
 const validPosition = findValidPosition(position, tempNodeId)
 const nodeTypeInfo = nodeTypesStore.getNodeType(type)
 const displayName = nodeTypeInfo?.display_name || type.replace(/_/g, ' ')
 // 根据节点类型设置默认配置
 const defaultConfigs: Record<string, Record<string, any>> = {
 ai_prompt: {
 user_prompt: '{{global.description}}',
 model: 'claude-3-5-sonnet-20241022',
 temperature: 0.7,
 max_tokens: 4096,
 output_format: 'text',
 },
 ai_coding_dispatcher: {
 max_tasks: 5,
 task_granularity: 'medium',
 include_tests: true,
 auto_assign_repos: false,
 },
 feishu_event_trigger: {
 event_types:,
 },
 fetch_work_item: {
 work_item_id: '{{input.work_item_id}}',
 extract_fields: ['description', 'title'],
 },
 }
 const newNode: Node = {
 id: crypto.randomUUID,
 type,
 position: validPosition, // Use collision-free position
 label: displayName,
 data: {
 node_type: type,
 name: displayName,
 config: defaultConfigs[type] || {},
 description: nodeTypeInfo?.description || '',
 },
 }
 store.addNode(newNode)
}
// Load node types on mount
onMounted( => {
 nodeTypesStore.fetchNodeTypes
})
// Watch collision warning and add/remove class on node elements
watch(collisionWarningNodeId, (newId, oldId) => {
 // Remove class from old node
 if (oldId) {
 const oldNode = document.querySelector(`[data-id="${oldId}"]`)
 if (oldNode) {
 oldNode.classList.remove('collision-warning')
 }
 }
 // Add class to new node
 if (newId) {
 const newNode = document.querySelector(`[data-id="${newId}"]`)
 if (newNode) {
 newNode.classList.add('collision-warning')
 }
 }
})
// Watch isColliding to show red glow on dragging node
watch(isColliding, (colliding) => {
 if (colliding) {
 // Add visual feedback to currently dragging node
 const draggingNode = document.querySelector('.vue-flow__node.dragging')
 if (draggingNode) {
 draggingNode.classList.add('collision-blocked')
 }
 } else {
 // Remove from all nodes
 document.querySelectorAll('.collision-blocked').forEach(el => {
 el.classList.remove('collision-blocked')
 })
 }
})
</script>
<template>
 <div
 class="h-full w-full workflow-canvas relative":class="{ 'drag-over': isDragOver }"
 @drop="onDrop"
 @dragover="onDragOver"
 @dragleave="onDragLeave"
 >
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/10 to-secondary/20 rounded-full blur-3xl" />
 <div class="absolute bottom-0 -left-40 w-96 bg-gradient-to-tr from-secondary/15 to-primary/5 rounded-full blur-3xl" />
 <div class="absolute top-1/3 right-1/4 w-64 bg-gradient-to-t from-violet-500/5 to-transparent rounded-full blur-3xl" />
 </div>
 <VueFlow
 v-model:nodes="nodes"
 v-model:edges="edges":node-types="nodeTypes":edge-types="edgeTypes":default-edge-options="defaultEdgeOptions":default-viewport="{ zoom: 1, x: 50, y: 50 }":min-zoom="0.2":max-zoom="4":nodes-draggable="editable":nodes-connectable="editable":elements-selectable="true":snap-to-grid="true":snap-grid="[20, 20]":connect-on-click="false":fit-view-on-init="false":pan-on-drag="true":zoom-on-scroll="true"
 class="vue-flow-wrapper"
 @connect="handleConnect"
 @node-drag-start="handleNodeDragStart"
 @node-drag="handleNodeDrag"
 @node-drag-stop="handleNodeDragStop"
 @node-click="handleNodeClick"
 @pane-click="handlePaneClick"
 >
 <!-- 背景网格 -->
 <Background
 variant="dots":gap="20":size="1"
 pattern-color="hsl(219 30% 65% / 0.4)"
 />
 <!-- 小地图 -->
 <MiniMap:pannable="true":zoomable="true"
 class="vue-flow-minimap"
 />
 <!-- 控制按钮 -->
 <Controls:show-interactive="false" />
 <!-- Grid overlay during drag -->
 <template v-if="isNodeDragging">
 <div class="grid-overlay" />
 </template>
 </VueFlow>
 <!-- Node preview position indicator -->
 <div
 v-if="isNodeDragging && previewPosition"
 class="node-preview":style="{
 transform: `translate(${previewPosition.x}px, ${previewPosition.y}px)`,
 }"
 />
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
 background: linear-gradient(135deg, hsl(210 40% 98%) 0%, hsl(220 30% 96%) 100%);
}
.workflow-canvas.drag-over {
 background: linear-gradient(135deg, hsl(210 60% 97%) 0%, hsl(220 50% 95%) 100%);
}
.vue-flow-wrapper {
 width: 100%;
 height: 100%;
}
/* Node 选中状态 */
.vue-flow .vue-flow__node.selected {
 outline: none;
}
/* Minimap 样式优化 */
.vue-flow-minimap {
 background: hsl(var(--card) / 0.8) !important;
 backdrop-filter: blur(8px);
 border: 1px solid hsl(var(--border) / 0.5) !important;
 border-radius: 12px !important;
}
/* Controls 样式优化 */
.vue-flow__controls {
 background: hsl(var(--card) / 0.8) !important;
 backdrop-filter: blur(8px);
 border: 1px solid hsl(var(--border) / 0.5) !important;
 border-radius: 12px !important;
 overflow: hidden;
}
.vue-flow__controls-button {
 background: transparent !important;
 border: none !important;
 border-bottom: 1px solid hsl(var(--border) / 0.3) !important;
}
.vue-flow__controls-button:last-child {
 border-bottom: none !important;
}
.vue-flow__controls-button:hover {
 background: hsl(var(--accent)) !important;
}
/* ========== Gradient Edge Styles ========== */
/* Gradient edge path animations */
.vue-flow__edge-path {
 transition: stroke-width 0.2s ease;
}
.vue-flow__edge.selected .vue-flow__edge-path {
 stroke-width: 4;
}
/* Glow layer animation on hover */
.vue-flow__edge:hover .vue-flow__edge-path-glow {
 opacity: 0.6;
}
/* ========== Drag Preview Styles ========== */
/* Grid overlay during drag */
.grid-overlay {
 position: absolute;
 inset: 0;
 pointer-events: none;
 background-image:
 linear-gradient(hsl(var(--primary) / 0.08) 1px, transparent 1px),
 linear-gradient(90deg, hsl(var(--primary) / 0.08) 1px, transparent 1px);
 background-size: 20px 20px;
 z-index: 1;
 opacity: 0;
 animation: gridFadeIn 0.15s ease forwards;
}
@keyframes gridFadeIn {
 to { opacity: 1; }
}
/* Node preview indicator */
.node-preview {
 position: absolute;
 top: 0;
 left: 0;
 width: 200px;
 height: 80px;
 pointer-events: none;
 opacity: 0.4;
 border: 2px dashed hsl(var(--primary));
 border-radius: 16px;
 background: hsl(var(--primary) / 0.05);
 z-index: 5;
 transition: transform 0.1s ease-out;
}
/* Node preview collision indicator */
.node-preview.collision {
 border-color: hsl(0 84% 60%);
 background: hsl(0 84% 60% / 0.1);
}
/* ========== Collision Warning Styles ========== */
/* Collision warning toast animation */
@keyframes slideUp {
 from {
 opacity: 0;
 transform: translate(-50%, 10px);
 }
 to {
 opacity: 1;
 transform: translate(-50%, 0);
 }
}
.workflow-canvas [class*="bg-destructive"] {
 animation: slideUp 0.2s ease-out;
}
</style>
