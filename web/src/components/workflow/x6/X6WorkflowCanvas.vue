<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useGraph } from './useGraph'
import { useDnd } from './useDnd'
import { registerAllNodes } from './nodeRegistry'
/**
 * X6 Workflow Canvas Component
 *
 * Renders an X6 graph canvas with:
 * - Dot grid background for visual alignment
 * - Mouse drag to pan the canvas
 * - Ctrl/Cmd + mousewheel to zoom
 * - Vue component nodes via x6-vue-shape
 * - Drag-and-drop node creation from sidebar
 *
 * The graph instance is managed by the useGraph composable,
 * which handles lifecycle (init on mount, dispose on unmount).
 */
// Register all node shapes before graph creation
registerAllNodes
const containerRef = ref<HTMLDivElement>
const { graph } = useGraph(containerRef, {
 // Enable selection for testing node selection state styling
 selecting: true,
})
// Initialize Dnd plugin for drag-and-drop from sidebar
const { initDnd, startDrag } = useDnd(graph)
// Initialize Dnd after graph is ready
watch(graph, (g) => {
 if (g) {
 initDnd
 }
}, { immediate: true })
/**
 * Handle drag start from sidebar node palette.
 * Creates a node configuration and starts the Dnd operation.
 *
 * @param nodeType - The shape type of the node being dragged
 * @param event - The MouseEvent that triggered the drag
 */
function handleDragStart(nodeType: string, event: MouseEvent) {
 startDrag({
 shape: nodeType,
 width: 200,
 height: 80,
 data: { name: 'New Node', description: '' },
 }, event)
}
// Add demo nodes for visual testing (Phase verification)
onMounted( => {
 watch(graph, (g) => {
 if (!g) return
 // Add demo nodes with different node types
 g.addNode({
 id: 'trigger-1',
 shape: 'manual_trigger',
 x: 100,
 y: 100,
 data: { name: 'Manual Trigger', description: 'Start workflow manually' },
 })
 g.addNode({
 id: 'action-1',
 shape: 'http_request',
 x: 100,
 y: 250,
 data: { name: 'HTTP Request', description: 'Call external API' },
 })
 g.addNode({
 id: 'condition-1',
 shape: 'condition',
 x: 100,
 y: 400,
 data: { name: 'Check Status', description: 'Branch based on response' },
 })
 }, { immediate: true })
})
// Expose graph instance and drag handler for parent components
defineExpose({
 graph,
 handleDragStart,
 startDrag,
})
</script>
<template>
 <div class="relative w-full h-full overflow-hidden">
 <!-- X6 Graph container - must have explicit dimensions via parent -->
 <div
 ref="containerRef"
 class="absolute inset-0"
 />
 </div>
</template>
