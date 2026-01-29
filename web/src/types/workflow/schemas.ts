import { z } from 'zod'
// ============================================================================
// 共享选项常量
// ============================================================================
/** AI 模型选项（默认模型列表，用于未配置自定义 API 时） */
export const AI_MODELS = [
 { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
 { value: 'claude-3-7-sonnet-20250219', label: 'Claude 3.7 Sonnet' },
 { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
 { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
 { value: 'gpt-4o', label: 'GPT-4o' },
 { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
 { value: 'gpt-4-turbo', label: ' Turbo' },
] as const
/** 输出格式选项 */
export const OUTPUT_FORMATS = [
 { value: 'text', label: '纯文本' },
 { value: 'json', label: 'JSON' },
 { value: 'markdown', label: 'Markdown' },
] as const
/** 任务粒度选项 */
export const TASK_GRANULARITY_OPTIONS = [
 { value: 'fine', label: '细粒度', description: '拆分为多个小任务' },
 { value: 'medium', label: '中粒度', description: '平衡任务数量和复杂度' },
 { value: 'coarse', label: '粗粒度', description: '合并为少量大任务' },
] as const
/** 工作项类型选项 */
export const WORK_ITEM_TYPE_OPTIONS = [
 { value: 'story', label: '需求 (Story)' },
 { value: 'task', label: '任务 (Task)' },
 { value: 'bug', label: '缺陷 (Bug)' },
] as const
/** 工作项类型选项（含全部） */
export const WORK_ITEM_TYPE_OPTIONS_WITH_ALL = [
 { value: '__all__', label: '全部类型' },
 ...WORK_ITEM_TYPE_OPTIONS,
] as const
/** 飞书事件类型选项 */
export const FEISHU_EVENT_TYPE_OPTIONS = [
 { value: 'WorkitemCreateEvent', label: '工作项创建' },
 { value: 'WorkitemStatusEvent', label: '状态变更' },
 { value: 'WorkitemCommentEvent', label: '评论事件' },
 { value: 'WorkitemUpdateEvent', label: '字段更新' },
 { value: 'WorkFlowNodeStatusEvent', label: '节点流转' },
] as const
/** 工作项字段选项 */
export const WORK_ITEM_FIELD_OPTIONS = [
 { value: 'description', label: '需求描述' },
 { value: 'prd_url', label: '需求文档链接' },
 { value: 'tech_doc_url', label: '技术方案链接' },
 { value: 'title', label: '标题' },
 { value: 'status', label: '状态' },
 { value: 'assignee', label: '负责人' },
 { value: 'priority', label: '优先级' },
] as const
// ============================================================================
// Zod Schemas
// ============================================================================
/** AI Prompt 节点配置 */
export const aiPromptConfigSchema = z.object({
 // API 配置
 use_custom_api: z.boolean.default(false),
 api_base_url: z.string.default(''),
 api_key: z.string.default(''),
 // 提示词配置
 system_prompt: z.string.default(''),
 user_prompt: z.string.default(''),
 // 模型配置
 model: z.string.default('claude-sonnet-4-20250514'),
 temperature: z.number.min(0).max(2).default(0.7),
 max_tokens: z.number.min(100).max(100000).default(4096),
 output_format: z.enum(['text', 'json', 'markdown']).default('text'),
})
/** AI 编码指派器节点配置 */
export const aiCodingDispatcherConfigSchema = z.object({
 // API 配置
 use_custom_api: z.boolean.default(false),
 api_base_url: z.string.default(''),
 api_key: z.string.default(''),
 // 模型配置
 analysis_model: z.string.default('claude-sonnet-4-20250514'),
 max_tasks: z.number.min(1).max(20).default(5),
 task_granularity: z.enum(['fine', 'medium', 'coarse']).default('medium'),
 include_tests: z.boolean.default(true),
 auto_assign_repos: z.boolean.default(true),
})
/** 获取工作项节点配置 */
export const fetchWorkItemConfigSchema = z.object({
 work_item_id: z.string.default(''),
 work_item_type: z.enum(['story', 'task', 'bug']).default('story'),
 extract_fields: z.array(z.string).default(['description', 'prd_url', 'tech_doc_url']),
 set_global_params: z.boolean.default(true),
 include_project_info: z.boolean.default(true),
 include_repositories: z.boolean.default(true),
})
/** 飞书事件触发器配置 */
export const feishuEventTriggerConfigSchema = z.object({
 event_types: z.array(z.string).default,
 filter_project_key: z.string.default(''),
 filter_work_item_type: z.enum(['story', 'task', 'bug', '']).default(''),
 filter_status: z.string.default(''),
})
// ============================================================================
// 类型推导
// ============================================================================
export type AIPromptConfig = z.infer<typeof aiPromptConfigSchema>
export type AICodingDispatcherConfig = z.infer<typeof aiCodingDispatcherConfigSchema>
export type FetchWorkItemConfig = z.infer<typeof fetchWorkItemConfigSchema>
export type FeishuEventTriggerConfig = z.infer<typeof feishuEventTriggerConfigSchema>
/** 所有节点配置的联合类型 */
export type NodeConfig =
 | AIPromptConfig
 | AICodingDispatcherConfig
 | FetchWorkItemConfig
 | FeishuEventTriggerConfig
// ============================================================================
// Schema 映射
// ============================================================================
/** 节点类型到 Schema 的映射 */
export const NODE_CONFIG_SCHEMAS = {
 ai_prompt: aiPromptConfigSchema,
 ai_coding_dispatcher: aiCodingDispatcherConfigSchema,
 fetch_work_item: fetchWorkItemConfigSchema,
 feishu_event_trigger: feishuEventTriggerConfigSchema,
} as const
export type NodeTypeWithSchema = keyof typeof NODE_CONFIG_SCHEMAS
