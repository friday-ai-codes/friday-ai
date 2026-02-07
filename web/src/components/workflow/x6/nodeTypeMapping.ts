// ============================================================================
// Node Type Mapping Configuration
// ============================================================================
/**
 * Configuration for mapping between X6 shapes and workflow types
 */
export interface NodeTypeConfig {
 shape: string
 workflowType: string
 category: 'trigger' | 'action' | 'condition'
 defaultData: Record<string, unknown>
}
/**
 * Node type mapping registry
 * Maps X6 shape names to workflow node types and their default configurations
 */
export const nodeTypeMapping: NodeTypeConfig = [
 // Triggers
 {
 shape: 'manual_trigger',
 workflowType: 'manual_trigger',
 category: 'trigger',
 defaultData: {},
 },
 {
 shape: 'webhook_trigger',
 workflowType: 'webhook_trigger',
 category: 'trigger',
 defaultData: {},
 },
 {
 shape: 'feishu_event_trigger',
 workflowType: 'feishu_event_trigger',
 category: 'trigger',
 defaultData: { event_types: },
 },
 // Actions
 {
 shape: 'http_request',
 workflowType: 'http_request',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'ai_prompt',
 workflowType: 'ai_prompt',
 category: 'action',
 defaultData: {
 model: 'claude-3-5-sonnet-20241022',
 temperature: 0.7,
 max_tokens: 4096,
 output_format: 'text',
 },
 },
 {
 shape: 'ai_coding_dispatcher',
 workflowType: 'ai_coding_dispatcher',
 category: 'action',
 defaultData: {
 max_tasks: 5,
 task_granularity: 'medium',
 include_tests: true,
 auto_assign_repos: false,
 },
 },
 {
 shape: 'fetch_work_item',
 workflowType: 'fetch_work_item',
 category: 'action',
 defaultData: {
 extract_fields: ['description', 'title'],
 },
 },
 // Conditions
 {
 shape: 'condition',
 workflowType: 'condition',
 category: 'condition',
 defaultData: {},
 },
]
/**
 * Get workflow type from X6 shape name
 */
export function getWorkflowType(shape: string): string {
 return nodeTypeMapping.find(m => m.shape === shape)?.workflowType ?? shape
}
/**
 * Get X6 shape name from workflow type
 */
export function getShape(workflowType: string): string {
 return nodeTypeMapping.find(m => m.workflowType === workflowType)?.shape ?? workflowType
}
/**
 * Get default data for a node type
 */
export function getDefaultData(nodeType: string): Record<string, unknown> {
 return nodeTypeMapping.find(m => m.workflowType === nodeType || m.shape === nodeType)?.defaultData ?? {}
}
/**
 * Get category for a node type
 */
export function getCategory(nodeType: string): 'trigger' | 'action' | 'condition' | undefined {
 return nodeTypeMapping.find(m => m.workflowType === nodeType || m.shape === nodeType)?.category
}
