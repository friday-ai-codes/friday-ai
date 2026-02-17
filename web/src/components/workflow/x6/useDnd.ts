import type { Graph, Node } from '@antv/x6'
import type { ShallowRef } from 'vue'
import { Dnd } from '@antv/x6'
import { onUnmounted, shallowRef } from 'vue'
import { generateShortId } from '~/utils/shortId'
/**
 * Node configuration for drag-and-drop operations.
 */
export interface DndNodeConfig {
 /** Node shape type */
 shape: string
 /** Node width */
 width?: number
 /** Node height */
 height?: number
 /** Node data */
 data?: Record<string, unknown>
 /** Additional node properties */
 [key: string]: unknown
}
/**
 * Composable for managing X6 Dnd plugin instance lifecycle.
 *
 * IMPORTANT: Uses shallowRef to prevent Vue's deep reactivity from
 * breaking Dnd internals (same pattern as useGraph.ts).
 *
 * @param graphRef - ShallowRef to the Graph instance
 * @returns Object containing dnd ref and control functions
 *
 * @example
 * ```vue
 * <script setup lang="ts">
 * const containerRef = ref<HTMLDivElement>
 * const { graph } = useGraph(containerRef)
 * const { dnd, initDnd, startDrag } = useDnd(graph)
 *
 * onMounted( => {
 * initDnd
 * })
 *
 * function handleDragStart(nodeType: string, event: MouseEvent) {
 * startDrag({
 * shape: 'workflow-node',
 * width: 240,
 * height: 80,
 * data: { type: nodeType }
 * }, event)
 * }
 * </script>
 * ```
 */
export function useDnd(graphRef: ShallowRef<Graph | null>) {
 // CRITICAL: Use shallowRef to avoid Vue's deep reactivity proxy
 // wrapping the Dnd instance, which breaks its internal state.
 const dnd = shallowRef<Dnd | null>(null)
 /**
 * Initialize the Dnd plugin instance.
 * Must be called after the Graph is initialized.
 */
 function initDnd {
 if (!graphRef.value) {
 return
 }
 const dndInstance = new Dnd({
 target: graphRef.value,
 /**
 * Configure the drag preview node.
 * Sets isDragPreview: true so Vue shape components can render
 * with reduced opacity during drag.
 */
 getDragNode(node: Node) {
 const cloned = node.clone({ keepId: false })
 const existingData = cloned.getData || {}
 cloned.setData({ ...existingData, isDragPreview: true })
 return cloned
 },
 /**
 * Configure the dropped node.
 * Use the same ID from drag preview (X6 generated UUID).
 */
 getDropNode(node: Node) {
 const cloned = node.clone({ keepId: true })
 const existingData = cloned.getData || {}
 cloned.setData({ ...existingData, isDragPreview: false })
 return cloned
 },
 })
 dnd.value = dndInstance
 }
 /**
 * Start a drag operation with the given node configuration.
 *
 * @param nodeConfig - Configuration for the node being dragged
 * @param event - The MouseEvent that triggered the drag
 */
 function startDrag(nodeConfig: DndNodeConfig, event: MouseEvent) {
 if (!dnd.value) {
 return
 }
 if (!graphRef.value) {
 return
 }
 // Create a temporary node for dragging with a generated shortId
 const shortId = generateShortId
 const node = graphRef.value.createNode({
 ...nodeConfig,
 data: {
 ...nodeConfig.data,
 shortId, // For display in node component
 },
 })
 // Start the drag operation
 dnd.value.start(node, event)
 }
 onUnmounted( => {
 // Dnd plugin doesn't have a dispose method, just null the ref
 // to allow garbage collection
 dnd.value = null
 })
 return {
 /** The X6 Dnd plugin instance (null before init, null after unmount) */
 dnd,
 /** Initialize the Dnd plugin (call after Graph is ready) */
 initDnd,
 /** Start a drag operation with node configuration */
 startDrag,
 }
}
