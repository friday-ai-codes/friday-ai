// ============================================================================
// X6-Compatible Store Types
// ============================================================================
/**
 * Simple workflow node type for composables and components.
 * Framework-agnostic representation used by design-time variable discovery,
 * schema validation, and other utilities.
 */
export interface WorkflowNode {
 id: string
 type?: string
 label?: string
 position: { x: number, y: number }
 data?: {
 node_type?: string
 name?: string
 [key: string]: unknown
 }
}
/**
 * Simple workflow edge type for composables and components.
 * Framework-agnostic representation used by DAG traversal and validation.
 */
export interface WorkflowEdge {
 id: string
 source: string
 target: string
 sourceHandle?: string
 targetHandle?: string
}
/**
 * Store-side node representation (X6-agnostic)
 * This is the canonical format for nodes in the Pinia store.
 * Converted to/from X6 Cell format by useX6Sync composable.
 *
 * - id: UUID for internal use (X6, API, database)
 * - shortId: Human-friendly ID for display and template variables (e.g., {{nodes.abc.field}})
 */
export interface WorkflowNodeStore {
 id: string // UUID
 shortId: string // 3-char human-friendly ID for display
 nodeType: string // maps to X6 shape
 name: string
 description: string
 position: { x: number, y: number }
 config: Record<string, unknown>
 // 错误处理配置
 onError: 'abort' | 'retry' | 'ignore'
 retryTimes: number
 retryDelay: number
 nodeTimeoutSeconds: number | null
 fallbackValues: Record<string, unknown> | null
 runCondition: Record<string, unknown> | null
 metadata: Record<string, unknown>
}
/**
 * Store-side edge representation (X6-agnostic)
 * This is the canonical format for edges in the Pinia store.
 * Converted to/from X6 Edge format by useX6Sync composable.
 */
export interface WorkflowEdgeStore {
 id: string
 source: string // source node ID
 sourcePort: string // source port ID
 target: string // target node ID
 targetPort: string // target port ID
 vertices?: Array<{ x: number, y: number }>
 label?: string
 condition: Record<string, unknown> | null
}
