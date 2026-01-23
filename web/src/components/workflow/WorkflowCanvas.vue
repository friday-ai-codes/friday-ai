<script setup lang="ts">
import type { Connection, Edge, Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted } from 'vue'
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
// Expose nodes and edges to VueFlow via v-model
const _nodesRef = nodes
const _edgesRef = edges
const { onConnect, onNodeDragStop, project, onNodeClick, onPaneClick } = useVueFlow
// Node Types Registration
const nodeTypes = {
 manual_trigger: markRaw(TriggerNode),
 webhook_trigger: markRaw(TriggerNode),
 schedule_trigger: markRaw(TriggerNode),
 http_request: markRaw(ActionNode),
 code_implement: markRaw(ActionNode),
 create_branch: markRaw(ActionNode),
 human_approval: markRaw(ApprovalNode),
 approval: markRaw(ApprovalNode),
 condition: markRaw(ControlNode),
 delay: markRaw(ControlNode),
 parallel: markRaw(ControlNode),
}
// Event Handlers
onConnect((connection: Connection) => {
 const newEdge: Edge = {
 id: `e-${connection.source}-${connection.target}-${Date.now}`,
 source: connection.source,
 target: connection.target,
 sourceHandle: connection.sourceHandle || 'default',
 targetHandle: connection.targetHandle || 'default',
 }
 store.addEdge(newEdge)
})
onNodeDragStop((e) => {
 store.updateNode(e.node.id, { position: e.node.position })
})
onNodeClick((e) => {
 store.selectNode(e.node.id)
})
onPaneClick( => {
 store.selectNode(null)
})
// Drag and Drop
function onDragOver(event: DragEvent) {
 event.preventDefault
 if (event.dataTransfer) {
 event.dataTransfer.dropEffect = 'move'
 }
}
function onDrop(event: DragEvent) {
 const type = event.dataTransfer?.getData('application/vueflow')
 if (!type)
 return
 const { left, top } = (event.currentTarget as HTMLElement).getBoundingClientRect
 const position = project({
 x: event.clientX - left,
 y: event.clientY - top,
 })
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
 description: '',
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
 <div class="h-full w-full bg-background" @drop="onDrop" @dragover="onDragOver">
 <VueFlow:node-types="nodeTypes":default-viewport="{ zoom: 1 }":min-zoom="0.2":max-zoom="4":nodes-draggable="editable":nodes-connectable="editable":elements-selectable="true"
 >
 <Background pattern-color="#aaa":gap="8" />
 <MiniMap />
 <Controls />
 </VueFlow>
 </div>
</template>
<style scoped>
.vue-flow__minimap {
 transform: scale(75%);
 transform-origin: bottom right;
}
</style>
