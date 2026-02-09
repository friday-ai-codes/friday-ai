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
 shape: 'schedule_trigger',
 workflowType: 'schedule_trigger',
 category: 'trigger',
 defaultData: { cron: '0 0 * * *' },
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
 shape: 'code_implement',
 workflowType: 'code_implement',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'create_branch',
 workflowType: 'create_branch',
 category: 'action',
 defaultData: {},
 },
 {
 shape: 'wait_feishu',
 workflowType: 'wait_feishu',
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
 shape: 'technical_plan',
 workflowType: 'technical_plan',
 category: 'action',
 defaultData: {},
 },
 // AI Agent (Friday 编码助手)
 {
 shape: 'ai_agent',
 workflowType: 'ai_agent',
 category: 'action',
 defaultData: {
 system_prompt: '你是一个专业的软件开发助手。你可以使用各种工具来完成编码任务，包括读写文件、执行命令、搜索代码等。请根据用户的需求，自主规划并执行任务。',
 user_prompt: '',
 enabled_tools:,
 max_iterations: 25,
 timeout_hours: 24,
 },
 },
 // Conditions
 {
 shape: 'condition',
 workflowType: 'condition',
 category: 'condition',
 defaultData: {},
 },
 {
 shape: 'approval',
 workflowType: 'approval',
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
