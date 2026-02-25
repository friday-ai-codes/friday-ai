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
 // Data Fetch
 {
 shape: 'fetch_work_item',
 workflowType: 'fetch_work_item',
 category: 'action',
 defaultData: { extract_fields: ['description', 'title'] },
 },
 {
 shape: 'fetch_project_info',
 workflowType: 'fetch_project_info',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'context_retrieval',
 workflowType: 'context_retrieval',
 category: 'action',
 defaultData: {},
 },
 // Actions
 {
 shape: 'http_request',
 workflowType: 'http_request',
 category: 'action',
 defaultData: { method: 'GET', url: '', headers: {} },
 },
 {
 shape: 'create_branch',
 workflowType: 'create_branch',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'create_pr',
 workflowType: 'create_pr',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'merge_pr',
 workflowType: 'merge_pr',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'notify_feishu',
 workflowType: 'notify_feishu',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'mcp_deploy',
 workflowType: 'mcp_deploy',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'wait_feishu_field',
 workflowType: 'wait_feishu_field',
 category: 'action',
 defaultData: {},
 },
 // AI
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
 shape: 'ai_variable_extractor',
 workflowType: 'ai_variable_extractor',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'variable_extractor',
 workflowType: 'variable_extractor',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'ai_plan_generation',
 workflowType: 'ai_plan_generation',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'ai_plan_approval',
 workflowType: 'ai_plan_approval',
 category: 'condition',
 defaultData: {},
 },
 {
 shape: 'ai_coding',
 workflowType: 'ai_coding',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'ai_code_review',
 workflowType: 'ai_code_review',
 category: 'action',
 defaultData: {},
 },
 // Conditions
 {
 shape: 'condition',
 workflowType: 'condition',
 category: 'condition',
 defaultData: {},
 },
 {
 shape: 'human_approval',
 workflowType: 'human_approval',
 category: 'condition',
 defaultData: {},
 },
 // Control flow
 {
 shape: 'delay',
 workflowType: 'delay',
 category: 'action',
 defaultData: { duration_seconds: 60 },
 },
 {
 shape: 'parallel',
 workflowType: 'parallel',
 category: 'action',
 defaultData: { branches: ['branch_0', 'branch_1'] },
 },
 {
 shape: 'join',
 workflowType: 'join',
 category: 'action',
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
