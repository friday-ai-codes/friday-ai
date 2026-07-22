import { z } from 'zod'

// ============================================================================
// 共享选项常量
// ============================================================================

/** AI 模型选项（默认模型列表，用于未配置自定义 API 时） */
export const AI_MODELS = [
  { value: '', label: '使用系统默认' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-3-7-sonnet-20250219', label: 'Claude 3.7 Sonnet' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
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
  { value: 'WorkitemCreateEvent', label: '工作项创建', description: '监听工作项创建事件' },
  { value: 'WorkitemStatusEvent', label: '状态变更', description: '监听工作项状态流转' },
  { value: 'WorkitemCommentEvent', label: '评论事件', description: '监听工作项评论' },
  { value: 'WorkitemUpdateEvent', label: '字段更新', description: '监听工作项字段修改' },
  { value: 'WorkFlowNodeStatusEvent', label: '节点流转', description: '监听飞书工作流节点状态' },
  { value: 'WorkitemFinishEvent', label: '工作项完成', description: '监听工作项完成' },
  { value: 'WorkitemDeleteEvent', label: '工作项删除', description: '监听工作项删除' },
  { value: 'WorkitemAbortedEvent', label: '工作项终止', description: '监听工作项被终止' },
  { value: 'WorkitemRestoreEvent', label: '工作项恢复', description: '监听工作项恢复' },
] as const

/** 常用状态选项（供快速选择） */
export const COMMON_STATUS_OPTIONS = [
  { value: 'open', label: '待处理', category: 'todo' },
  { value: 'in_progress', label: '进行中', category: 'doing' },
  { value: 'done', label: '已完成', category: 'done' },
  { value: 'closed', label: '已关闭', category: 'done' },
  { value: 'pending_review', label: '待审核', category: 'doing' },
  { value: 'approved', label: '已通过', category: 'done' },
  { value: 'rejected', label: '已拒绝', category: 'done' },
  { value: 'blocked', label: '已阻塞', category: 'doing' },
] as const

/** 常用字段快捷选项 */
export const QUICK_FIELD_OPTIONS = [
  { key: 'prdUrl', name: '需求文档', path: '$.fields[?(@.key==\'field_bcff9b\')].value', desc: 'PRD 文档链接' },
  { key: 'techDocUrl', name: '技术方案', path: '$.fields[?(@.key==\'field_3f6667\')].value', desc: '技术方案文档链接' },
  { key: 'description', name: '描述', path: '$.fields[?(@.key==\'description\')].value', desc: '工作项描述' },
  { key: 'workItemName', name: '工作项名称', path: '$.name', desc: '工作项标题' },
  { key: 'workItemId', name: '工作项ID', path: '$.id', desc: '工作项唯一标识' },
  { key: 'projectKey', name: '项目Key', path: '$.project_key', desc: '飞书项目标识' },
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
  use_custom_api: z.boolean().default(false),
  api_base_url: z.string().default(''),
  api_key: z.string().default(''),
  // Provider 凭证:指向 ProviderCredential.id;null 走系统默认
  provider_credential_id: z.string().uuid('凭证 ID 格式无效').nullable().optional(),
  // 提示词配置
  system_prompt: z.string().default(''),
  user_prompt: z.string().default(''),
  // 模型配置
  model: z.string().default(''),
  temperature: z.number().min(0, '不能小于 0').max(2, '不能大于 2').default(0.7),
  max_tokens: z.number().min(100, '不能小于 100').max(100000, '不能大于 100000').default(4096),
  output_format: z.enum(['text', 'json', 'markdown'], '请选择有效的选项').default('text'),
  // 高级设置
  max_thinking_tokens: z.number().int().min(1024, '不能小于 1024').max(128000, '不能大于 128000').nullable().optional(),
  max_budget_usd: z.number().min(0.01, '不能小于 0.01').max(100, '不能大于 100').nullable().optional(),
})

/** AI 编码指派器节点配置 - 严格模式 */
export const aiCodingDispatcherConfigSchema = z.object({
  // 严格模式只需要合并选项
  merge_same_branch: z.boolean().default(true),
})

/** 获取工作项节点配置 */
export const fetchWorkItemConfigSchema = z.object({
  work_item_id: z.string().default(''),
  work_item_type: z.enum(['story', 'task', 'bug', '__auto__'], '请选择有效的选项').default('__auto__'),
})

/** 飞书事件触发器配置
 *
 * 纯 Webhook 入口：触发时机与过滤完全由飞书侧自动化规则决定，节点本身不再配置
 * 事件类型 / 工作项类型 / 状态 / 空间等条件。保存工作流后，服务端回填专属端点
 * token（`endpoint_token`，只读），前端据此拼出完整端点 URL 展示给用户。
 */
export const feishuEventTriggerConfigSchema = z.object({
  // 服务端生成的专属端点 token（只读展示，用户无需填写）
  endpoint_token: z.string().default(''),
  // 节点专属校验 token（拖入时客户端生成）：飞书规则需随请求发送，webhook 命中端点后比对，
  // 不匹配则拒绝触发（纵深防御）。
  verification_token: z.string().default(''),
})

/** 提取规则 */
export const extractionRuleSchema = z.object({
  source_path: z.string().min(1, 'JSONPath 路径不能为空'),
  key: z.string().regex(/^[a-z_]\w*$/i, '变量标识符格式不正确'),
  name: z.string().min(1, '显示名称不能为空'),
  desc: z.string().default(''),
  required: z.boolean().default(false),
})

/** 变量提取节点配置 */
export const variableExtractorConfigSchema = z.object({
  extractions: z.array(extractionRuleSchema).default([]),
})

/** AI 变量定义 */
export const aiVariableDefinitionSchema = z.object({
  key: z.string().regex(/^[a-z_]\w*$/i, '变量标识符格式不正确'),
  name: z.string().min(1, '显示名称不能为空'),
  desc: z.string().min(1, '提取描述不能为空'),
  required: z.boolean().default(false),
})

/** AI 变量提取节点配置 */
export const aiVariableExtractorConfigSchema = z.object({
  // API 配置
  use_custom_api: z.boolean().default(false),
  api_base_url: z.string().default(''),
  api_key: z.string().default(''),
  // Provider 凭证:指向 ProviderCredential.id;null 走系统默认
  provider_credential_id: z.string().uuid('凭证 ID 格式无效').nullable().optional(),
  // 提取配置
  input_source: z.string().default(''),
  variables: z.array(aiVariableDefinitionSchema).default([]),
  additional_prompt: z.string().default(''),
  model: z.string().default(''),
  // 高级设置
  max_thinking_tokens: z.number().int().min(1024, '不能小于 1024').max(128000, '不能大于 128000').nullable().optional(),
  max_budget_usd: z.number().min(0.01, '不能小于 0.01').max(100, '不能大于 100').nullable().optional(),
})

/** 召回上下文节点配置 */
export const contextRetrievalConfigSchema = z.object({
  query: z.string().default(''),
  // Support both string (JSONPath expression like "{{$.input.repositories[*].id}}")
  // and array (legacy format or direct UUIDs)
  repositories: z.union([z.string(), z.array(z.string())]).default(''),
  top_k: z.number().min(1, '不能小于 1').max(50, '不能大于 50').default(10),
  score_threshold: z.number().min(0, '不能小于 0').max(1, '不能大于 1').default(0.5),
  language_filter: z.string().default(''),
  include_content: z.boolean().default(true),
  format_as_markdown: z.boolean().default(true),
})

/** 交付知识检索节点配置 */
export const deliveryKnowledgeSearchConfigSchema = z.object({
  query: z.string().default(''),
  top_k: z.number().min(1).max(20).default(5),
  project_ids: z.array(z.string()).default([]),
  repository_ids: z.array(z.string()).default([]),
  entity_kinds: z.array(z.string()).default([]),
  as_of: z.string().default(''),
  include_superseded: z.boolean().default(false),
})

/** 获取项目信息节点配置 */
export const fetchSpaceInfoConfigSchema = z.object({
  project_identifier: z.string().default(''),
  identifier_type: z.enum(['auto', 'id', 'feishu_project_key'], '请选择有效的选项').default('auto'),
  include_repositories: z.boolean().default(true),
  include_feishu_config: z.boolean().default(false),
  include_claude_config: z.boolean().default(false),
  include_webhook_token: z.boolean().default(false),
})

/** 等待条件 */
export const waitConditionSchema = z.object({
  field: z.string().default(''),
  operator: z.enum(['eq', 'ne', 'contains', 'not_contains', 'is_empty', 'is_not_empty', 'gt', 'gte', 'lt', 'lte', 'regex'], '请选择有效的选项').default('eq'),
  value: z.string().default(''),
})

/** 等待条件组 */
export const waitConditionGroupSchema = z.object({
  logic: z.enum(['and', 'or'], '请选择有效的选项').default('and'),
  conditions: z.array(waitConditionSchema).default([]),
})

/** 等待飞书字段节点配置 */
export const waitFeishuFieldConfigSchema = z.object({
  work_item_id: z.string().default('{{trigger.work_item_id}}'),
  work_item_type: z.enum(['story', 'task', 'bug', 'epic'], '请选择有效的选项').default('story'),
  project_key: z.string().default('{{trigger.project_key}}'),
  condition: waitConditionGroupSchema.default({ logic: 'and', conditions: [] }),
  timeout_seconds: z.number().default(0),
  timeout_action: z.enum(['fail', 'skip', 'retry'], '请选择有效的选项').default('fail'),
})

/** 创建分支节点配置 */
export const createBranchConfigSchema = z.object({
  repositories: z.array(z.string()).default([]),
  branch_name: z.string().default(''),
  base_branch: z.string().default('main'),
  checkout: z.boolean().default(true),
  push: z.boolean().default(false),
})

/** 创建 PR 节点配置 */
export const createPRConfigSchema = z.object({
  repositories: z.array(z.string()).default([]),
  title: z.string().default(''),
  body: z.string().default(''),
  head_branch: z.string().default(''),
  base_branch: z.string().default('main'),
  draft: z.boolean().default(false),
  add_cross_references: z.boolean().default(true),
})

/** AI 方案生成节点配置 */
export const aiPlanGenerationConfigSchema = z.object({
  // Prompts
  system_prompt: z.string().default(''),
  user_prompt: z.string().default(''),

  // Repository filtering
  include_repos: z.array(z.string()).default([]),
  exclude_repos: z.array(z.string()).default([]),

  // Execution limits
  max_iterations: z.number().min(10, '不能小于 10').max(200, '不能大于 200').default(50),
  enabled_tools: z.array(z.string()).default([]),
  auto_inject_similar_history: z.boolean().default(true),
  similar_history_top_k: z.number().min(1).max(20).default(5),
  similar_history_as_of: z.string().default(''),

  // Feishu integration
  chat_id: z.string().default(''),

  // API configuration
  use_custom_api: z.boolean().default(false),
  api_base_url: z.string().default(''),
  api_key: z.string().default(''),
  model: z.string().default(''),
  // Provider 凭证:指向 ProviderCredential.id;null 走系统默认
  provider_credential_id: z.string().uuid('凭证 ID 格式无效').nullable().optional(),
})

/** AI 编码执行节点配置 */
export const aiCodingConfigSchema = z.object({
  container_image: z.string().default('friday/claude-code:latest'),
  timeout_seconds: z.number().int().min(60, '不能小于 60').max(7200, '不能大于 7200').default(1800),
  chat_id: z.string().default(''),
  polling_interval: z.number().int().min(5, '不能小于 5').max(60, '不能大于 60').default(15),
  // 与后端 config_schema 模板默认一致：新建节点默认开；存量工作流缺键走后端 fallback 守门
  write_back: z.boolean().default(true),
})

/** 全局变量结构 */
export const globalVariableSchema = z.object({
  key: z.string(),
  name: z.string(),
  desc: z.string().optional(),
  value: z.any(),
  required: z.boolean().optional(),
  source_node: z.string().optional(),
})

// ============================================================================
// 类型推导
// ============================================================================

export type AIPromptConfig = z.infer<typeof aiPromptConfigSchema>
export type AICodingDispatcherConfig = z.infer<typeof aiCodingDispatcherConfigSchema>
export type FetchWorkItemConfig = z.infer<typeof fetchWorkItemConfigSchema>
export type FeishuEventTriggerConfig = z.infer<typeof feishuEventTriggerConfigSchema>
export type ExtractionRule = z.infer<typeof extractionRuleSchema>
export type VariableExtractorConfig = z.infer<typeof variableExtractorConfigSchema>
export type AIVariableDefinition = z.infer<typeof aiVariableDefinitionSchema>
export type AIVariableExtractorConfig = z.infer<typeof aiVariableExtractorConfigSchema>
export type ContextRetrievalConfig = z.infer<typeof contextRetrievalConfigSchema>
export type DeliveryKnowledgeSearchConfig = z.infer<typeof deliveryKnowledgeSearchConfigSchema>
export type FetchSpaceInfoConfig = z.infer<typeof fetchSpaceInfoConfigSchema>
export type WaitCondition = z.infer<typeof waitConditionSchema>
export type WaitConditionGroup = z.infer<typeof waitConditionGroupSchema>
export type WaitFeishuFieldConfig = z.infer<typeof waitFeishuFieldConfigSchema>
export type CreateBranchConfig = z.infer<typeof createBranchConfigSchema>
export type CreatePRConfig = z.infer<typeof createPRConfigSchema>
export type AIPlanGenerationConfig = z.infer<typeof aiPlanGenerationConfigSchema>
export type AICodingConfig = z.infer<typeof aiCodingConfigSchema>
export type GlobalVariable = z.infer<typeof globalVariableSchema>

/** 所有节点配置的联合类型 */
export type NodeConfig
  = | AIPromptConfig
    | AICodingDispatcherConfig
    | FetchWorkItemConfig
    | FeishuEventTriggerConfig
    | VariableExtractorConfig
    | AIVariableExtractorConfig
    | ContextRetrievalConfig
    | DeliveryKnowledgeSearchConfig
    | FetchSpaceInfoConfig
    | WaitFeishuFieldConfig
    | CreateBranchConfig
    | CreatePRConfig
    | AIPlanGenerationConfig
    | AICodingConfig

// ============================================================================
// Schema 映射
// ============================================================================

/** 节点类型到 Schema 的映射 */
export const NODE_CONFIG_SCHEMAS = {
  ai_prompt: aiPromptConfigSchema,
  ai_coding_dispatcher: aiCodingDispatcherConfigSchema,
  fetch_work_item: fetchWorkItemConfigSchema,
  feishu_event_trigger: feishuEventTriggerConfigSchema,
  variable_extractor: variableExtractorConfigSchema,
  ai_variable_extractor: aiVariableExtractorConfigSchema,
  context_retrieval: contextRetrievalConfigSchema,
  delivery_knowledge_search: deliveryKnowledgeSearchConfigSchema,
  fetch_space_info: fetchSpaceInfoConfigSchema,
  wait_feishu_field: waitFeishuFieldConfigSchema,
  create_branch: createBranchConfigSchema,
  create_pr: createPRConfigSchema,
  ai_plan_generation: aiPlanGenerationConfigSchema,
  ai_coding: aiCodingConfigSchema,
} as const

export type NodeTypeWithSchema = keyof typeof NODE_CONFIG_SCHEMAS
