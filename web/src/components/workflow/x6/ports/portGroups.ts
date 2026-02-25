/**
 * Port group configuration interface.
 * Defines position and visual attributes for a group of ports.
 */
export interface PortGroupConfig {
 position: 'left' | 'right' | 'top' | 'bottom' | {
 name: string
 args?: Record<string, unknown>
 }
 attrs: {
 circle: Record<string, unknown>
 }
 markup?: Array<{
 tagName: string
 selector: string
 }>
}
/**
 * Port metadata interface for X6 nodes.
 * Matches X6's Node.PortMetadata structure.
 */
export interface PortMetadata {
 id: string
 group: string
 attrs?: {
 circle?: Record<string, unknown>
 }
}
/**
 * Standard port groups for workflow nodes.
 * Input ports on left, output ports on right.
 * Edges anchor to the port circle, not the node center.
 * Using absolute positioning to ensure vertical centering.
 */
export const workflowPortGroups: Record<string, PortGroupConfig> = {
 input: {
 position: {
 name: 'absolute',
 args: {
 x: 0,
 y: '50%',
 },
 },
 markup: [
 {
 tagName: 'circle',
 selector: 'circle',
 },
 ],
 attrs: {
 circle: {
 'r': 6,
 'magnet': true,
 'stroke': 'var(--color-border)',
 'strokeWidth': 1.5,
 'fill': 'var(--color-background)',
 'data-port-direction': 'input',
 },
 },
 },
 output: {
 position: {
 name: 'absolute',
 args: {
 x: '100%',
 y: '50%',
 },
 },
 markup: [
 {
 tagName: 'circle',
 selector: 'circle',
 },
 ],
 attrs: {
 circle: {
 'r': 6,
 'magnet': true,
 'stroke': 'var(--color-border)',
 'strokeWidth': 1.5,
 'fill': 'var(--color-background)',
 'data-port-direction': 'output',
 },
 },
 },
}
/**
 * Generate port items based on input/output names.
 * Creates port metadata with type information stored in attrs.
 *
 * @param _nodeType - The node type (used for future schema lookup)
 * @param inputs - Array of input port names
 * @param outputs - Array of output port names
 * @returns Array of port metadata items
 */
export function generatePortItems(
 _nodeType: string,
 inputs: string,
 outputs: string,
): PortMetadata {
 const items: PortMetadata =
 // Input ports
 inputs.forEach((inputName, index) => {
 items.push({
 id: `input-${index}`,
 group: 'input',
 attrs: {
 circle: {
 'data-port-name': inputName,
 'data-port-type': 'any',
 },
 },
 })
 })
 // Output ports
 outputs.forEach((outputName, index) => {
 items.push({
 id: `output-${index}`,
 group: 'output',
 attrs: {
 circle: {
 'data-port-name': outputName,
 'data-port-type': 'any',
 },
 },
 })
 })
 return items
}
/**
 * Node types that are trigger nodes (no inputs, one output).
 */
const TRIGGER_NODE_TYPES = [
 'manual_trigger',
 'webhook_trigger',
 'feishu_event_trigger',
]
/**
 * Node types that are condition nodes (one input, two outputs for branches).
 */
const CONDITION_NODE_TYPES = ['condition', 'human_approval']
/**
 * Node types that have error output ports (1 input, 2 outputs: default + error).
 */
const ERROR_OUTPUT_NODE_TYPES = [
 'create_branch',
 'create_pr',
 'merge_pr',
 'notify_feishu',
 'mcp_deploy',
]
/**
 * Get default port configuration for a node type.
 * - Trigger nodes: 0 inputs, 1 output
 * - Condition nodes: 1 input, 2 outputs (true/false branches)
 * - Error output nodes: 1 input, 2 outputs (default/error)
 * - Action nodes: 1 input, 1 output
 *
 * @param nodeType - The node type to get ports for
 * @returns Array of port metadata items
 */
export function getDefaultPortsForNodeType(nodeType: string): PortMetadata {
 if (TRIGGER_NODE_TYPES.includes(nodeType)) {
 return generatePortItems(nodeType,, ['output'])
 }
 // ai_plan_approval: 1 input, 2 outputs (approved/rejected)
 if (nodeType === 'ai_plan_approval') {
 return generatePortItems(nodeType, ['input'], ['approved', 'rejected'])
 }
 if (CONDITION_NODE_TYPES.includes(nodeType)) {
 return generatePortItems(nodeType, ['input'], ['true', 'false'])
 }
 if (ERROR_OUTPUT_NODE_TYPES.includes(nodeType)) {
 return generatePortItems(nodeType, ['input'], ['default', 'error'])
 }
 if (nodeType === 'parallel') {
 return generatePortItems(nodeType, ['input'], ['branch_0', 'branch_1'])
 }
 if (nodeType === 'join') {
 return generatePortItems(nodeType, ['input_0', 'input_1'], ['output'])
 }
 // Action nodes: one input, one output
 return generatePortItems(nodeType, ['input'], ['output'])
}
