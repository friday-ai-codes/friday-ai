<script setup lang="ts">
import { ref, watch } from 'vue'
import { useGraph } from './useGraph'
import { useDnd } from './useDnd'
import { useHistory } from './useHistory'
import { useMinimap } from './useMinimap'
import { useX6Sync } from './useX6Sync'
import { registerAllNodes } from './nodeRegistry'
import EditorToolbar from './toolbar/EditorToolbar.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
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
 * - Minimap navigation panel
 * - Bidirectional sync with Pinia store
 *
 * The graph instance is managed by the useGraph composable,
 * which handles lifecycle (init on mount, dispose on unmount).
 */
// Register all node shapes before graph creation
registerAllNodes
const store = useWorkflowsStore
const containerRef = ref<HTMLDivElement>
const minimapContainerRef = ref<HTMLDivElement>
const { graph } = useGraph(containerRef, {
 // Enable selection for testing node selection state styling
 selecting: true,
})
// Initialize editor enhancement composables
const { canUndo, canRedo, undo, redo } = useHistory(graph)
useMinimap(graph, minimapContainerRef)
// Initialize bidirectional sync between X6 and Pinia store
const { loadFromStore } = useX6Sync(graph)
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
// Initialize Dnd and event listeners after graph is ready
watch(graph, (g) => {
 if (g) {
 initDnd
 // Node click → open config panel
 g.on('node:click', ({ node }) => {
 store.selectNode(node.id)
 })
 // Click on blank area → close config panel
 g.on('blank:click', => {
 store.selectNode(null)
 })
 // Delete/Backspace → remove selected cells
 g.bindKey(['delete', 'backspace'], => {
 const cells = g.getSelectedCells
 if (cells.length > 0) {
 g.removeCells(cells)
 }
 return false
 })
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
// Expose graph instance, drag handler, and loadFromStore for parent components
defineExpose({
 graph,
 handleDragStart,
 startDrag,
 loadFromStore,
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
