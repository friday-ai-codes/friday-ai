<script setup lang="ts">
import type { Connection, Edge, Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MarkerType, VueFlow, useVueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted, ref } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
// Custom Nodes
import ActionNode from './nodes/ActionNode.vue'
import AICodingDispatcherNode from './nodes/AICodingDispatcherNode.vue'
import AIPromptNode from './nodes/AIPromptNode.vue'
import ApprovalNode from './nodes/ApprovalNode.vue'
import ControlNode from './nodes/ControlNode.vue'
import FeishuEventTriggerNode from './nodes/FeishuEventTriggerNode.vue'
import FetchWorkItemNode from './nodes/FetchWorkItemNode.vue'
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
// 使用 useVueFlow 获取 project 方法
const { project } = useVueFlow
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
 // AI
 ai_prompt: markRaw(AIPromptNode),
 ai_coding_dispatcher: markRaw(AICodingDispatcherNode),
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
 if (!connection.source || !connection.target)
 return
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
 position,
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
</style>
