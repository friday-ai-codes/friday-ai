import type { Node } from '@vue-flow/core'
import { computed, ref } from 'vue'
interface DragState {
 nodeId: string
 originalPosition: { x: number; y: number }
 previewPosition: { x: number; y: number }
 isDragging: boolean
}
/**
 * Composable for managing drag preview state with grid snapping.
 * Provides visual feedback during node drag operations.
 */
export function useDragPreview(gridSize: number = 20) {
 const dragState = ref<DragState | null>(null)
 const isDragging = computed( => dragState.value?.isDragging ?? false)
 const draggingNodeId = computed( => dragState.value?.nodeId ?? null)
 const previewPosition = computed( => dragState.value?.previewPosition ?? null)
 const originalPosition = computed( => dragState.value?.originalPosition ?? null)
 /**
 * Snap a position to the nearest grid intersection
 */
 function snapToGrid(pos: { x: number; y: number }) {
 return {
 x: Math.round(pos.x / gridSize) * gridSize,
 y: Math.round(pos.y / gridSize) * gridSize,
 }
 }
 /**
 * Called when node drag starts
 */
 function onDragStart(node: Node) {
 dragState.value = {
 nodeId: node.id,
 originalPosition: { ...node.position },
 previewPosition: snapToGrid(node.position),
 isDragging: true,
 }
 }
 /**
 * Called during node drag to update preview position
 */
 function onDrag(node: Node) {
 if (dragState.value && dragState.value.nodeId === node.id) {
 dragState.value.previewPosition = snapToGrid(node.position)
 }
 }
 /**
 * Called when node drag stops
 * Returns the snapped position for the node
 */
 function onDragStop: { x: number; y: number } | null {
 const snappedPosition = dragState.value?.previewPosition ?? null
 dragState.value = null
 return snappedPosition
 }
 return {
 isDragging,
 draggingNodeId,
 previewPosition,
 originalPosition,
 onDragStart,
 onDrag,
 onDragStop,
 snapToGrid,
 }
}
