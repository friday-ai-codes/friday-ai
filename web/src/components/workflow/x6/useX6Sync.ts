import type { Edge, Graph, Node } from '@antv/x6'
import type { ShallowRef } from 'vue'
import type { WorkflowEdgeStore, WorkflowNodeStore } from '~/types/workflow'
import { onUnmounted, watch } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getDefaultData, getShape, getWorkflowType } from './nodeTypeMapping'
/**
 * Bidirectional sync between X6 Graph and Pinia Store.
 *
 * Sync direction per CONTEXT.md:
 * - X6 → Store: Graph events (node:added, node:moved, edge:connected, etc.)
 * - Store → X6: Watch store.nodes/edges for external changes
 *
 * Conflict resolution: X6 priority (canvas operations win)
 * Sync scope: Graph structure + business data (NOT view state like zoom/pan)
 */
export function useX6Sync(graph: ShallowRef<Graph | null>) {
 const store = useWorkflowsStore
 // Flags to prevent sync loops
 let isSyncingFromX6 = false
 let isSyncingToX6 = false
 // Store event cleanup functions
 const cleanupFns: ( => void) =
 /**
 * Convert X6 Node to Store format
 * New nodes from canvas don't have shortId yet - it will be assigned by backend
 */
 function nodeToStoreFormat(node: Node): WorkflowNodeStore {
 const data = node.getData || {}
 const position = node.getPosition
 const shape = node.shape
 return {
 id: node.id,
 shortId: data.shortId || '', // Empty for new nodes, filled by backend
 nodeType: getWorkflowType(shape),
 name: data.name || 'Untitled',
 description: data.description || '',
 position: { x: position.x, y: position.y },
 config: data.config || getDefaultData(shape),
 timeout: data.timeout ?? null,
 retryCount: data.retryCount ?? 0,
 retryDelay: data.retryDelay ?? 60,
 runCondition: data.runCondition ?? null,
 metadata: data.metadata || {},
 }
 }
 /**
 * Convert X6 Edge to Store format
 */
 function edgeToStoreFormat(edge: Edge): WorkflowEdgeStore {
 const source = edge.getSourceCell
 const target = edge.getTargetCell
 const sourcePort = edge.getSourcePortId
 const targetPort = edge.getTargetPortId
 const vertices = edge.getVertices
 const data = edge.getData || {}
 return {
 id: edge.id,
 source: source?.id || '',
 sourcePort: sourcePort || 'default',
 target: target?.id || '',
 targetPort: targetPort || 'default',
 vertices: vertices?.length ? vertices: undefined,
 label: edge.getLabels?.[0]?.attrs?.label?.text as string | undefined,
 condition: data.condition ?? null,
 }
 }
 /**
 * Setup X6 event listeners for X6 → Store sync
 */
 function setupX6Listeners(g: Graph) {
 // Node added
 g.on('node:added', ({ node }) => {
 if (isSyncingToX6) {
 return
 }
 isSyncingFromX6 = true
 const storeNode = nodeToStoreFormat(node)
 // @ts-expect-error Method removed in Phase; file deleted in Phase
 store.addNodeFromX6(storeNode)
 isSyncingFromX6 = false
 })
 // Node removed
 g.on('node:removed', ({ node }) => {
 if (isSyncingToX6)
 return
 isSyncingFromX6 = true
 store.removeNode(node.id)
 isSyncingFromX6 = false
 })
 // Node position changed (after drag ends)
 g.on('node:moved', ({ node }) => {
 if (isSyncingToX6)
 return
 isSyncingFromX6 = true
 store.updateNodePosition(node.id, node.getPosition)
 isSyncingFromX6 = false
 })
 // Node data changed (config updates from panel)
 g.on('cell:change:data', ({ cell }) => {
 if (isSyncingToX6)
 return
 if (cell.isNode) {
 isSyncingFromX6 = true
 const data = cell.getData
 store.updateNodeData(cell.id, data)
 isSyncingFromX6 = false
 }
 })
 // Edge connected (new connection created)
 g.on('edge:connected', ({ edge }) => {
 if (isSyncingToX6)
 return
 // Only sync if edge has valid source and target
 const source = edge.getSourceCell
 const target = edge.getTargetCell
 if (source && target) {
 isSyncingFromX6 = true
 // @ts-expect-error Method removed in Phase; file deleted in Phase
 store.addEdgeFromX6(edgeToStoreFormat(edge))
 isSyncingFromX6 = false
 }
 })
 // Edge removed
 g.on('edge:removed', ({ edge }) => {
 if (isSyncingToX6)
 return
 isSyncingFromX6 = true
 store.removeEdge(edge.id)
 isSyncingFromX6 = false
 })
 }
 /**
 * Load nodes and edges from store into X6 graph.
 * Used when loading a workflow from backend.
 */
 function loadFromStore(g: Graph) {
 isSyncingToX6 = true
 // Clear existing cells
 g.clearCells
 // Add nodes
 for (const node of store.nodes) {
 g.addNode({
 id: node.id,
 shape: getShape(node.nodeType),
 x: node.position.x,
 y: node.position.y,
 data: {
 shortId: node.shortId, // For display in node component
 name: node.name,
 description: node.description,
 config: node.config,
 timeout: node.timeout,
 retryCount: node.retryCount,
 retryDelay: node.retryDelay,
 runCondition: node.runCondition,
 metadata: node.metadata,
 },
 })
 }
 // Add edges
 for (const edge of store.edges) {
 g.addEdge({
 id: edge.id,
 shape: 'gradient-edge',
 source: { cell: edge.source, port: edge.sourcePort },
 target: { cell: edge.target, port: edge.targetPort },
 vertices: edge.vertices,
 data: { condition: edge.condition },
 labels: edge.label ? [{ attrs: { label: { text: edge.label } } }]:,
 })
 }
 isSyncingToX6 = false
 }
 /**
 * Initialize sync when graph becomes available
 */
 const stopGraphWatch = watch(graph, (g) => {
 if (g) {
 setupX6Listeners(g)
 // If store already has data (workflow loaded), render it
 if (store.nodes.length > 0 || store.edges.length > 0) {
 loadFromStore(g)
 }
 }
 }, { immediate: true })
 cleanupFns.push(stopGraphWatch)
 /**
 * Watch store nodes for changes and sync to X6 (Store → X6)
 * This handles updates from NodeConfigPanel
 */
 const stopNodesWatch = watch(
 => store.nodes,
 (newNodes) => {
 if (isSyncingFromX6 || !graph.value)
 return
 isSyncingToX6 = true
 for (const node of newNodes) {
 const x6Node = graph.value.getCellById(node.id)
 if (x6Node?.isNode) {
 const currentData = x6Node.getData || {}
 // Only update if data actually changed
 if (
 currentData.name !== node.name
 || currentData.description !== node.description
 || JSON.stringify(currentData.config) !== JSON.stringify(node.config)
 ) {
 // Don't use silent: true, we need the node component to receive the change:data event
 x6Node.setData({
 ...currentData,
 name: node.name,
 description: node.description,
 config: node.config,
 })
 }
 }
 }
 isSyncingToX6 = false
 },
 { deep: true },
 )
 cleanupFns.push(stopNodesWatch)
 // Cleanup on unmount
 onUnmounted( => {
 cleanupFns.forEach(fn => fn)
 })
 return {
 /** Load store data into graph (call after fetchWorkflow) */
 loadFromStore: => {
 if (graph.value) {
 loadFromStore(graph.value)
 }
 },
 /** Check if currently syncing from X6 to store (for external use) */
 get isSyncingFromX6 {
 return isSyncingFromX6
 },
 /** Check if currently syncing from store to X6 (for external use) */
 get isSyncingToX6 {
 return isSyncingToX6
 },
 }
}
