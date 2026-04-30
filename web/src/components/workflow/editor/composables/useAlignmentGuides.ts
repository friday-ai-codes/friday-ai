import type { GraphNode, ViewportTransform } from '@vue-flow/core'
import type { Ref } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { ref } from 'vue'
export interface GuideLine {
 orientation: 'horizontal' | 'vertical'
 position: number
 type: 'center' | 'edge'
}
export interface AlignmentResult {
 x: number
 y: number
 guides: GuideLine
}
const SNAP_THRESHOLD = 5
const DEFAULT_NODE_WIDTH = 200
const DEFAULT_NODE_HEIGHT = 80
/**
 * Compute node bounds (width/height + position) from a VueFlow graph node.
 * Falls back to defaults if dimensions are not yet available.
 */
function getNodeBounds(node: GraphNode): { x: number, y: number, width: number, height: number, centerX: number, centerY: number } {
 const width = node.dimensions?.width ?? DEFAULT_NODE_WIDTH
 const height = node.dimensions?.height ?? DEFAULT_NODE_HEIGHT
 const x = node.computedPosition?.x ?? node.position.x
 const y = node.computedPosition?.y ?? node.position.y
 return {
 x,
 y,
 width,
 height,
 centerX: x + width / 2,
 centerY: y + height / 2,
 }
}
/**
 * Check if a node is within the visible viewport (with buffer).
 */
function isNodeInViewport(
 node: GraphNode,
 viewport: ViewportTransform,
 canvasWidth: number,
 canvasHeight: number,
): boolean {
 const bounds = getNodeBounds(node)
 // Convert viewport to canvas coordinates
 const visibleLeft = -viewport.x / viewport.zoom
 const visibleTop = -viewport.y / viewport.zoom
 const visibleRight = visibleLeft + canvasWidth / viewport.zoom
 const visibleBottom = visibleTop + canvasHeight / viewport.zoom
 // Add buffer equal to node size
 return (
 bounds.x + bounds.width > visibleLeft - bounds.width
 && bounds.x < visibleRight + bounds.width
 && bounds.y + bounds.height > visibleTop - bounds.height
 && bounds.y < visibleBottom + bounds.height
 )
}
/**
 * Composable for alignment guides during node drag.
 *
 * Usage in WorkflowCanvas.vue:
 * ```ts
 * const { alignmentGuides, checkAlignment, clearGuides } = useAlignmentGuides
 * // In onNodesChange position handler:
 * const result = checkAlignment(draggedNodeId, change.position)
 * change.position = { x: result.x, y: result.y }
 * ```
 */
export function useAlignmentGuides {
 const { getNodes, viewport } = useVueFlow
 const alignmentGuides: Ref<GuideLine> = ref
 /**
 * Check alignment of dragged node against all other visible nodes.
 * Returns the snapped position and the alignment guides to render.
 */
 function checkAlignment(draggedNodeId: string, position: { x: number, y: number }): AlignmentResult {
 const allNodes = getNodes.value
 const draggedNode = allNodes.find(n => n.id === draggedNodeId)
 if (!draggedNode) {
 alignmentGuides.value =
 return { x: position.x, y: position.y, guides: }
 }
 // Estimate dragged node dimensions (use existing or default)
 const draggedWidth = draggedNode.dimensions?.width ?? DEFAULT_NODE_WIDTH
 const draggedHeight = draggedNode.dimensions?.height ?? DEFAULT_NODE_HEIGHT
 const draggedBounds = {
 x: position.x,
 y: position.y,
 width: draggedWidth,
 height: draggedHeight,
 centerX: position.x + draggedWidth / 2,
 centerY: position.y + draggedHeight / 2,
 right: position.x + draggedWidth,
 bottom: position.y + draggedHeight,
 }
 const guides: GuideLine =
 let snapX = position.x
 let snapY = position.y
 let hasSnapX = false
 let hasSnapY = false
 // Get canvas dimensions for viewport filtering
 const canvasEl = document.querySelector('.vue-flow__transformationpane')?.parentElement
 const canvasWidth = canvasEl?.clientWidth ?? window.innerWidth
 const canvasHeight = canvasEl?.clientHeight ?? window.innerHeight
 for (const node of allNodes) {
 if (node.id === draggedNodeId) continue
 if (!isNodeInViewport(node, viewport.value, canvasWidth, canvasHeight)) continue
 const bounds = getNodeBounds(node)
 const targetRight = bounds.x + bounds.width
 const targetBottom = bounds.y + bounds.height
 // --- Horizontal alignments (affect X) ---
 // Vertical center alignment: dragged centerX ~ target centerX
 const centerXDiff = Math.abs(draggedBounds.centerX - bounds.centerX)
 if (centerXDiff < SNAP_THRESHOLD && !hasSnapX) {
 snapX = bounds.centerX - draggedWidth / 2
 hasSnapX = true
 guides.push({ orientation: 'vertical', position: bounds.centerX, type: 'center' })
 }
 // Left edge alignment: dragged x ~ target x
 const leftDiff = Math.abs(draggedBounds.x - bounds.x)
 if (leftDiff < SNAP_THRESHOLD && !hasSnapX) {
 snapX = bounds.x
 hasSnapX = true
 guides.push({ orientation: 'vertical', position: bounds.x, type: 'edge' })
 }
 // Right edge alignment: dragged right ~ target right
 const rightDiff = Math.abs(draggedBounds.right - targetRight)
 if (rightDiff < SNAP_THRESHOLD && !hasSnapX) {
 snapX = targetRight - draggedWidth
 hasSnapX = true
 guides.push({ orientation: 'vertical', position: targetRight, type: 'edge' })
 }
 // --- Vertical alignments (affect Y) ---
 // Horizontal center alignment: dragged centerY ~ target centerY
 const centerYDiff = Math.abs(draggedBounds.centerY - bounds.centerY)
 if (centerYDiff < SNAP_THRESHOLD && !hasSnapY) {
 snapY = bounds.centerY - draggedHeight / 2
 hasSnapY = true
 guides.push({ orientation: 'horizontal', position: bounds.centerY, type: 'center' })
 }
 // Top edge alignment: dragged y ~ target y
 const topDiff = Math.abs(draggedBounds.y - bounds.y)
 if (topDiff < SNAP_THRESHOLD && !hasSnapY) {
 snapY = bounds.y
 hasSnapY = true
 guides.push({ orientation: 'horizontal', position: bounds.y, type: 'edge' })
 }
 // Bottom edge alignment: dragged bottom ~ target bottom
 const bottomDiff = Math.abs(draggedBounds.bottom - targetBottom)
 if (bottomDiff < SNAP_THRESHOLD && !hasSnapY) {
 snapY = targetBottom - draggedHeight
 hasSnapY = true
 guides.push({ orientation: 'horizontal', position: targetBottom, type: 'edge' })
 }
 }
 alignmentGuides.value = guides
 return { x: snapX, y: snapY, guides }
 }
 function clearGuides {
 alignmentGuides.value =
 }
 return {
 alignmentGuides,
 checkAlignment,
 clearGuides,
 }
}
