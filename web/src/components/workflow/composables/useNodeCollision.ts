import type { Node } from '@vue-flow/core'
import { ref } from 'vue'
export interface NodeBounds {
 id: string
 x: number
 y: number
 width: number
 height: number
}
export interface CollisionResult {
 collides: boolean
 nearestDistance: number
 collidingNodeId: string | null
 isNearBoundary: boolean // within 30px but not colliding
}
const COLLISION_MARGIN = 30
const DEFAULT_NODE_WIDTH = 200
const DEFAULT_NODE_HEIGHT = 80
/**
 * Extended node type with optional dimensions (available on GraphNode at runtime)
 */
interface NodeWithDimensions extends Node {
 dimensions?: { width: number; height: number }
}
/**
 * Get bounding box for a node
 */
export function getNodeBounds(node: Node): NodeBounds {
 const nodeWithDims = node as NodeWithDimensions
 return {
 id: node.id,
 x: node.position.x,
 y: node.position.y,
 width: nodeWithDims.dimensions?.width ?? DEFAULT_NODE_WIDTH,
 height: nodeWithDims.dimensions?.height ?? DEFAULT_NODE_HEIGHT,
 }
}
/**
 * Check collision between a dragging node and other nodes
 * Uses AABB (Axis-Aligned Bounding Box) collision detection
 */
export function checkCollision(
 draggingBounds: NodeBounds,
 otherNodes: NodeBounds,
 margin: number = COLLISION_MARGIN
): CollisionResult {
 let nearestDistance = Infinity
 let collidingNodeId: string | null = null
 let isNearBoundary = false
 for (const other of otherNodes) {
 if (other.id === draggingBounds.id) continue
 // Calculate gap between bounding boxes
 const gapX = Math.max(
 0,
 Math.max(
 other.x - (draggingBounds.x + draggingBounds.width),
 draggingBounds.x - (other.x + other.width)
 )
 )
 const gapY = Math.max(
 0,
 Math.max(
 other.y - (draggingBounds.y + draggingBounds.height),
 draggingBounds.y - (other.y + other.height)
 )
 )
 // Distance is 0 if boxes overlap, otherwise Euclidean distance of gaps
 const distance = gapX === 0 && gapY === 0
 ? 0: Math.sqrt(gapX * gapX + gapY * gapY)
 if (distance < nearestDistance) {
 nearestDistance = distance
 }
 // Check if within margin (collision)
 if (distance < margin) {
 collidingNodeId = other.id
 if (distance > 0) {
 isNearBoundary = true
 }
 }
 }
 return {
 collides: nearestDistance < margin,
 nearestDistance,
 collidingNodeId,
 isNearBoundary: isNearBoundary && nearestDistance > 0,
 }
}
/**
 * Composable for node collision detection with 30px minimum spacing
 */
export function useNodeCollision(nodesRef: => Node) {
 const collisionWarningNodeId = ref<string | null>(null)
 const isColliding = ref(false)
 /**
 * Check if a node at given position would collide with other nodes
 */
 function checkNodeCollision(
 nodeId: string,
 position: { x: number; y: number },
 dimensions?: { width: number; height: number }
 ): CollisionResult {
 const nodes = nodesRef
 const otherBounds = nodes
 .filter(n => n.id !== nodeId)
 .map(getNodeBounds)
 const draggingBounds: NodeBounds = {
 id: nodeId,
 x: position.x,
 y: position.y,
 width: dimensions?.width ?? DEFAULT_NODE_WIDTH,
 height: dimensions?.height ?? DEFAULT_NODE_HEIGHT,
 }
 const result = checkCollision(draggingBounds, otherBounds)
 isColliding.value = result.collides
 collisionWarningNodeId.value = result.isNearBoundary ? nodeId: null
 return result
 }
 /**
 * Store last valid position during drag
 */
 const lastValidPosition = ref<{ x: number; y: number } | null>(null)
 /**
 * Find a valid position near the desired position that doesn't collide
 * Uses expanding spiral pattern to find nearest valid spot
 */
 function findValidPosition(
 position: { x: number; y: number },
 nodeId: string,
 dimensions?: { width: number; height: number }
 ): { x: number; y: number } {
 // If no collision, return original position
 const result = checkNodeCollision(nodeId, position, dimensions)
 if (!result.collides) {
 return position
 }
 // Try to find nearest valid position using spiral pattern
 // Expand search to 500px to handle dense layouts
 const step = 20
 const maxOffset = 500
 for (let offset = step; offset <= maxOffset; offset += step) {
 // Try 8 directions at each distance level
 const candidates = [
 { x: position.x + offset, y: position.y },
 { x: position.x - offset, y: position.y },
 { x: position.x, y: position.y + offset },
 { x: position.x, y: position.y - offset },
 { x: position.x + offset, y: position.y + offset },
 { x: position.x - offset, y: position.y - offset },
 { x: position.x + offset, y: position.y - offset },
 { x: position.x - offset, y: position.y + offset },
 ]
 for (const candidate of candidates) {
 // Use a temporary check that doesn't update reactive state
 const nodes = nodesRef
 const otherBounds = nodes
 .filter(n => n.id !== nodeId)
 .map(getNodeBounds)
 const draggingBounds: NodeBounds = {
 id: nodeId,
 x: candidate.x,
 y: candidate.y,
 width: dimensions?.width ?? DEFAULT_NODE_WIDTH,
 height: dimensions?.height ?? DEFAULT_NODE_HEIGHT,
 }
 const check = checkCollision(draggingBounds, otherBounds)
 if (!check.collides) {
 return candidate
 }
 }
 }
 // Fallback: return original position (shouldn't happen in practice)
 return position
 }
 /**
 * Check collision and track last valid position for drag constraint
 */
 function checkAndConstrainPosition(
 nodeId: string,
 position: { x: number; y: number },
 dimensions?: { width: number; height: number }
 ): { position: { x: number; y: number }; collides: boolean; isNearBoundary: boolean } {
 const result = checkNodeCollision(nodeId, position, dimensions)
 if (!result.collides) {
 // Position is valid, update last valid position
 lastValidPosition.value = { ...position }
 return { position, collides: false, isNearBoundary: result.isNearBoundary }
 }
 // Colliding - return last valid position if available
 if (lastValidPosition.value) {
 return {
 position: lastValidPosition.value,
 collides: true,
 isNearBoundary: false,
 }
 }
 // No last valid position, return current (shouldn't happen normally)
 return { position, collides: true, isNearBoundary: false }
 }
 /**
 * Initialize last valid position when drag starts
 */
 function initDragPosition(position: { x: number; y: number }) {
 lastValidPosition.value = { ...position }
 }
 /**
 * Clear collision warning state
 */
 function clearWarning {
 collisionWarningNodeId.value = null
 isColliding.value = false
 }
 return {
 collisionWarningNodeId,
 isColliding,
 checkNodeCollision,
 findValidPosition,
 checkAndConstrainPosition,
 initDragPosition,
 clearWarning,
 }
}
