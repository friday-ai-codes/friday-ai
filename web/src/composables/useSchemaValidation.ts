import type { Node } from '@vue-flow/core'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
/**
 * Type compatibility matrix for workflow port connections
 * Uses loose matching: types are compatible if target accepts source type
 */
const TYPE_COMPATIBILITY: Record<string, string> = {
 string: ['string', 'any'],
 number: ['number', 'any'],
 boolean: ['boolean', 'any'],
 object: ['object', 'any'],
 array: ['array', 'any'],
 any: ['string', 'number', 'boolean', 'object', 'array', 'any'],
}
/**
 * Connection validation result
 */
export interface ConnectionCheckResult {
 valid: boolean
 warning?: string
}
/**
 * Port compatibility info for highlighting during drag
 */
export interface PortCompatibility {
 nodeId: string
 handleId: string
 compatible: boolean
}
/**
 * Check if two port types are compatible
 * @param sourceType - The output port type
 * @param targetType - The input port type
 * @returns true if types are compatible
 */
export function areTypesCompatible(sourceType: string, targetType: string): boolean {
 const source = sourceType.toLowerCase
 const target = targetType.toLowerCase
 // 'any' target accepts all types
 if (target === 'any') {
 return true
 }
 // Check if source type is in target's compatibility list
 const compatibleTypes = TYPE_COMPATIBILITY[source]
 if (compatibleTypes) {
 return compatibleTypes.includes(target)
 }
 // Unknown types: fallback to exact match
 return source === target
}
/**
 * Schema validation composable for workflow connections
 *
 * Provides type compatibility checking and connection validation
 * for the workflow editor.
 *
 * @example
 * ```ts
 * const { checkConnection, getCompatiblePorts } = useSchemaValidation
 *
 * // Check if a connection is valid
 * const result = checkConnection('ai_prompt', 'output', 'http_request', 'body')
 * if (result.warning) {
 * console.warn(result.warning)
 * }
 *
 * // Get compatible ports for highlighting during drag
 * const ports = getCompatiblePorts('node-1', 'string', nodes)
 * ```
 */
export function useSchemaValidation {
 const nodeTypesStore = useNodeTypesStore
 /**
 * Check if a connection between two ports is valid
 * Per CONTEXT.md: visual warning only, never block connections
 *
 * @param sourceNodeType - The source node's type (e.g., 'ai_prompt')
 * @param sourceHandle - The source port handle name
 * @param targetNodeType - The target node's type
 * @param targetHandle - The target port handle name
 * @returns Validation result with optional warning message
 */
 function checkConnection(
 sourceNodeType: string,
 sourceHandle: string,
 targetNodeType: string,
 targetHandle: string,
 ): ConnectionCheckResult {
 // Look up node type definitions
 const sourceNodeDef = nodeTypesStore.getNodeType(sourceNodeType)
 const targetNodeDef = nodeTypesStore.getNodeType(targetNodeType)
 // If either node type not found, allow connection (no schema info)
 if (!sourceNodeDef || !targetNodeDef) {
 return { valid: true }
 }
 // Find the source output port
 const sourcePort = sourceNodeDef.outputs.find(p => p.name === sourceHandle)
 // Find the target input port
 const targetPort = targetNodeDef.inputs.find(p => p.name === targetHandle)
 // If either port not found, allow connection (no schema info)
 if (!sourcePort || !targetPort) {
 return { valid: true }
 }
 // Check type compatibility
 const compatible = areTypesCompatible(sourcePort.type, targetPort.type)
 // Always return valid: true (per CONTEXT.md: visual warning only, never block)
 if (!compatible) {
 return {
 valid: true,
 warning: `类型不匹配: ${sourcePort.type} -> ${targetPort.type}`,
 }
 }
 return { valid: true }
 }
 /**
 * Get all compatible ports for highlighting during drag
 *
 * @param sourceNodeId - The node being dragged from
 * @param sourcePortType - The type of the source output port
 * @param nodes - All nodes in the workflow
 * @returns Array of port compatibility info for all input ports
 */
 function getCompatiblePorts(
 sourceNodeId: string,
 sourcePortType: string,
 nodes: Node,
 ): PortCompatibility {
 const result: PortCompatibility =
 for (const node of nodes) {
 // Skip the source node
 if (node.id === sourceNodeId) {
 continue
 }
 // Get node type definition
 const nodeTypeKey = node.data?.node_type || node.type
 if (!nodeTypeKey) continue
 const nodeTypeDef = nodeTypesStore.getNodeType(nodeTypeKey)
 if (!nodeTypeDef) continue
 // Check each input port
 for (const input of nodeTypeDef.inputs) {
 result.push({
 nodeId: node.id,
 handleId: input.name,
 compatible: areTypesCompatible(sourcePortType, input.type),
 })
 }
 }
 return result
 }
 return {
 areTypesCompatible,
 checkConnection,
 getCompatiblePorts,
 }
}
