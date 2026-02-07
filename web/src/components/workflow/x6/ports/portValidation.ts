import type { Cell } from '@antv/x6'
/**
 * Connecting configuration type for X6 Graph.
 * Matches a subset of Graph.Options['connecting'].
 */
export interface ConnectingConfig {
 allowBlank: boolean
 allowNode: boolean
 allowPort: boolean
 allowMulti: 'withPort' | boolean
 allowLoop: boolean
 snap: { radius: number }
 highlight: boolean
 router: string
 connector: string
 anchor: string
 connectionPoint: string
 validateConnection: (args: {
 sourceCell?: Cell | null
 targetCell?: Cell | null
 sourceMagnet?: Element | null
 targetMagnet?: Element | null
 }) => boolean
}
/**
 * Port type compatibility matrix.
 * Maps source type to compatible target types.
 */
const typeCompatibility: Record<string, string> = {
 any: ['any', 'string', 'number', 'boolean', 'object', 'array'],
 string: ['string', 'any'],
 number: ['number', 'any'],
 boolean: ['boolean', 'any'],
 object: ['object', 'any'],
 array: ['array', 'any'],
}
/**
 * Check if two port types are compatible for connection.
 * Defaults to 'any' if type is null/undefined.
 *
 * @param sourceType - The source port type
 * @param targetType - The target port type
 * @returns true if types are compatible
 */
export function arePortTypesCompatible(
 sourceType: string | null,
 targetType: string | null,
): boolean {
 // Default to 'any' if type not specified
 const src = sourceType || 'any'
 const tgt = targetType || 'any'
 // Check compatibility
 const compatibleTypes = typeCompatibility[src]
 if (!compatibleTypes) {
 return false
 }
 return compatibleTypes.includes(tgt)
}
/**
 * Get connecting configuration for X6 Graph.
 * Includes validation rules for port connections.
 *
 * @returns Graph connecting options with validation
 */
export function getConnectingConfig: ConnectingConfig {
 return {
 // Only allow connections to ports
 allowBlank: false,
 allowNode: false,
 allowPort: true,
 // Allow multiple edges if different ports
 allowMulti: 'withPort',
 // Prevent loops to same node
 allowLoop: false,
 // Snap to nearest port
 snap: { radius: 20 },
 // Highlight valid targets during drag
 highlight: true,
 // Use router for clean edge paths
 router: 'manhattan',
 connector: 'rounded',
 // Anchor edges to the port center (not node center)
 anchor: 'center',
 connectionPoint: 'anchor',
 // Validate connection on drag
 validateConnection({ sourceCell, targetCell, sourceMagnet, targetMagnet }) {
 // Must connect to a port (magnet)
 if (!sourceMagnet || !targetMagnet) {
 return false
 }
 // Prevent self-connection
 if (sourceCell?.id === targetCell?.id) {
 return false
 }
 // Get port directions
 const sourceDir = sourceMagnet.getAttribute('data-port-direction')
 const targetDir = targetMagnet.getAttribute('data-port-direction')
 // Must connect output to input
 if (sourceDir !== 'output' || targetDir !== 'input') {
 return false
 }
 // Get port types for compatibility check
 const sourceType = sourceMagnet.getAttribute('data-port-type')
 const targetType = targetMagnet.getAttribute('data-port-type')
 return arePortTypesCompatible(sourceType, targetType)
 },
 }
}
