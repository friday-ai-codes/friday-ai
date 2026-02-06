<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useGraph } from './useGraph'
import { useDnd } from './useDnd'
import { useHistory } from './useHistory'
import { useSnapline } from './useSnapline'
import { useMinimap } from './useMinimap'
import { registerAllNodes } from './nodeRegistry'
import EditorToolbar from './toolbar/EditorToolbar.vue'
/**
 * X6 Workflow Canvas Component
 *
 * Renders an X6 graph canvas with:
 * - Dot grid background for visual alignment
 * - Mouse drag to pan the canvas
 * - Ctrl/Cmd + mousewheel to zoom
 * - Vue component nodes via x6-vue-shape
 * - Drag-and-drop node creation from sidebar
 * - Undo/redo with keyboard shortcuts (Ctrl+Z, Ctrl+Shift+Z)
 * - Alignment snaplines when dragging nodes
 * - Minimap navigation panel
 *
 * The graph instance is managed by the useGraph composable,
 * which handles lifecycle (init on mount, dispose on unmount).
 */
// Register all node shapes before graph creation
registerAllNodes
const containerRef = ref<HTMLDivElement>
const minimapContainerRef = ref<HTMLDivElement>
const { graph } = useGraph(containerRef, {
 // Enable selection for testing node selection state styling
 selecting: true,
})
// Initialize editor enhancement composables
const { canUndo, canRedo, undo, redo } = useHistory(graph)
useSnapline(graph)
useMinimap(graph, minimapContainerRef)
// Zoom control functions
function zoomIn {
 graph.value?.zoom(0.1)
}
function zoomOut {
 graph.value?.zoom(-0.1)
}
function zoomFit {
 graph.value?.zoomToFit({ padding: 20 })
}
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
 <!-- Editor toolbar in top-left corner -->
 <EditorToolbar
 class="absolute left-4 top-4 z-10":can-undo="canUndo":can-redo="canRedo"
 @undo="undo"
 @redo="redo"
 @zoom-in="zoomIn"
 @zoom-out="zoomOut"
 @zoom-fit="zoomFit"
 />
 <!-- Minimap container in bottom-right corner with glassmorphism styling -->
 <div
 ref="minimapContainerRef"
 class="absolute right-4 bottom-4 z-10 rounded-xl
 bg-card/70 backdrop-blur-sm border border-border/50
 shadow-lg overflow-hidden"
 />
 </div>
</template>
