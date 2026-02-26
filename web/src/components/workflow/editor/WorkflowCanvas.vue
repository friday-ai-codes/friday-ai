<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow canvas wired to Pinia store.
 *
 * Phase: empty canvas + dot background.
 * Phase: real node/edge data from store via useWorkflowTransform.
 */
import type { NodeDragEvent, Connection } from '@vue-flow/core'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { toVueFlowNodes, toVueFlowEdges } from './composables/useWorkflowTransform'
import { nodeTypes } from './nodes'
const store = useWorkflowsStore
const { nodes: storeNodes, edges: storeEdges } = storeToRefs(store)
// Convert store data to VueFlow format (reactive)
const vfNodes = computed( => toVueFlowNodes(storeNodes.value))
const vfEdges = computed( => toVueFlowEdges(storeEdges.value))
// Sync position changes back to store (lightweight, no history)
function onNodeDragStop(event: NodeDragEvent) {
 for (const node of event.nodes) {
 store.updateNodePosition(node.id, node.position)
 }
}
// Sync new connections back to store
function onConnect(connection: Connection) {
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
 <VueFlow:nodes="vfNodes":edges="vfEdges":node-types="nodeTypes":fit-view-on-init="true"
 @node-drag-stop="onNodeDragStop"
 @connect="onConnect"
 >
 <Background
 variant="dots":gap="35":size="1.5"
 color="#3b82f620"
 />
 </VueFlow>
 </div>
</template>
