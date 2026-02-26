<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * Phase: basic canvas + dot background + store sync.
 * Phase: connection validation, gradient edges, sidebar drag-and-drop.
 */
import type { NodeDragEvent, Connection } from '@vue-flow/core'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { storeToRefs } from 'pinia'
import { computed, markRaw } from 'vue'
import { toast } from 'vue-sonner'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { toVueFlowNodes, toVueFlowEdges } from './composables/useWorkflowTransform'
import { useConnectionValidator, getValidationError } from './composables/useConnectionValidator'
import { useDragAndDrop } from './composables/useDragAndDrop'
import { nodeTypes } from './nodes'
import GradientEdge from './edges/GradientEdge.vue'
const store = useWorkflowsStore
const { nodes: storeNodes, edges: storeEdges } = storeToRefs(store)
const vfNodes = computed( => toVueFlowNodes(storeNodes.value))
const vfEdges = computed( => toVueFlowEdges(storeEdges.value))
const edgeTypes = { gradient: markRaw(GradientEdge) }
const { validateConnection } = useConnectionValidator
const { onDragOver, onDrop } = useDragAndDrop
function onNodeDragStop(event: NodeDragEvent) {
 for (const node of event.nodes) {
 store.updateNodePosition(node.id, node.position)
 }
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
</script>
<template>
 <div class="h-full w-full bg-background">
 <VueFlow:nodes="vfNodes":edges="vfEdges":node-types="nodeTypes":edge-types="edgeTypes":is-valid-connection="validateConnection":fit-view-on-init="true"
 @node-drag-stop="onNodeDragStop"
 @connect="onConnect"
 @dragover="onDragOver"
 @drop="onDrop"
 >
 <Background
 variant="dots":gap="35":size="1.5"
 color="#3b82f620"
 />
 </VueFlow>
 </div>
</template>
