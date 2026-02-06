import { Graph } from '@antv/x6'
/**
 * Node color mapping by category.
 * Colors match the gradient themes used in node components.
 */
export const NODE_COLORS = {
 trigger: '#3B82F6', // blue-500
 action: '#8B5CF6', // violet-500
 condition: '#F59E0B', // amber-500
 default: '#6B7280', // gray-500
} as const
/**
 * Get the color for a node based on its type.
 *
 * @param nodeType - The node type string (e.g., 'manual_trigger', 'http_request')
 * @returns The hex color for the node category
 */
export function getNodeColor(nodeType: string): string {
 // Trigger nodes (blue)
 if (nodeType.includes('trigger')) {
 return NODE_COLORS.trigger
 }
 // Condition/decision nodes (amber)
 if (nodeType === 'condition' || nodeType === 'approval') {
 return NODE_COLORS.condition
 }
 // All other nodes are actions (violet)
 return NODE_COLORS.action
}
/**
 * Register the gradient-edge shape with X6.
 * Must be called before creating a Graph that uses gradient edges.
 *
 * The gradient-edge inherits from the base edge and adds:
 * - Rounded connector for smooth curves
 * - Manhattan router for orthogonal paths
 * - Classic arrow marker at target
 */
export function registerGradientEdge: void {
 Graph.registerEdge(
 'gradient-edge',
 {
 inherit: 'edge',
 attrs: {
 line: {
 stroke: '#5B8FF9',
 strokeWidth: 2,
 targetMarker: {
 name: 'classic',
 size: 8,
 },
 },
 },
 connector: { name: 'rounded' },
 router: { name: 'manhattan' },
 },
 true, // Override if already registered
 )
}
/**
 * Apply a linear gradient to an edge based on source and target colors.
 *
 * Creates an SVG linearGradient element and applies it to the edge stroke.
 * The gradient follows the edge path from source to target.
 *
 * @param graph - The X6 Graph instance
 * @param edgeId - The ID of the edge to style
 * @param sourceColor - Hex color for the gradient start (source node)
 * @param targetColor - Hex color for the gradient end (target node)
 */
export function applyEdgeGradient(
 graph: Graph,
 edgeId: string,
 sourceColor: string,
 targetColor: string,
): void {
 const edge = graph.getCellById(edgeId)
 if (!edge || !edge.isEdge) {
 return
 }
 const gradientId = `edge-gradient-${edgeId}`
 // Get the SVG element from the graph view
 const svg = graph.view.svg
 if (!svg) {
 return
 }
 // Get or create defs element
 let defs = svg.querySelector('defs')
 if (!defs) {
 defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs')
 svg.insertBefore(defs, svg.firstChild)
 }
 // Remove existing gradient with same ID
 const existingGradient = defs.querySelector(`#${gradientId}`)
 if (existingGradient) {
 existingGradient.remove
 }
 // Get edge source and target points for gradient direction
 const sourcePoint = edge.getSourcePoint
 const targetPoint = edge.getTargetPoint
 // Create linear gradient
 const gradient = document.createElementNS(
 'http://www.w3.org/2000/svg',
 'linearGradient',
 )
 gradient.setAttribute('id', gradientId)
 gradient.setAttribute('gradientUnits', 'userSpaceOnUse')
 gradient.setAttribute('x1', String(sourcePoint.x))
 gradient.setAttribute('y1', String(sourcePoint.y))
 gradient.setAttribute('x2', String(targetPoint.x))
 gradient.setAttribute('y2', String(targetPoint.y))
 // Add color stops
 const stop1 = document.createElementNS(
 'http://www.w3.org/2000/svg',
 'stop',
 )
 stop1.setAttribute('offset', '0%')
 stop1.setAttribute('stop-color', sourceColor)
 const stop2 = document.createElementNS(
 'http://www.w3.org/2000/svg',
 'stop',
 )
 stop2.setAttribute('offset', '100%')
 stop2.setAttribute('stop-color', targetColor)
 gradient.appendChild(stop1)
 gradient.appendChild(stop2)
 defs.appendChild(gradient)
 // Apply gradient to edge stroke
 edge.attr('line/stroke', `url(#${gradientId})`)
}
/**
 * Apply gradient to an edge based on its connected nodes' types.
 *
 * Automatically determines colors from source and target node types
 * and applies the appropriate gradient.
 *
 * @param graph - The X6 Graph instance
 * @param edgeId - The ID of the edge to style
 */
export function applyEdgeGradientFromNodes(graph: Graph, edgeId: string): void {
 const edge = graph.getCellById(edgeId)
 if (!edge || !edge.isEdge) {
 return
 }
 const sourceNode = edge.getSourceNode
 const targetNode = edge.getTargetNode
 if (!sourceNode || !targetNode) {
 return
 }
 // Get node types from data or shape
 const sourceData = sourceNode.getData as { node_type?: string } | undefined
 const targetData = targetNode.getData as { node_type?: string } | undefined
 const sourceType = sourceData?.node_type || sourceNode.shape || 'default'
 const targetType = targetData?.node_type || targetNode.shape || 'default'
 const sourceColor = getNodeColor(sourceType)
 const targetColor = getNodeColor(targetType)
 applyEdgeGradient(graph, edgeId, sourceColor, targetColor)
}
