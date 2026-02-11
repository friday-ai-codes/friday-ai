import type { Component } from 'vue'
import type { ZodSchema } from 'zod'
import type { AICodeReviewConfig, AICodingConfig, AICodingDispatcherConfig, AIAgentConfig, AIPlanApprovalConfig, AIPlanGenerationConfig, AIPromptConfig, AIVariableExtractorConfig, ContextRetrievalConfig, CreateBranchConfig, CreatePRConfig, FeishuEventTriggerConfig, FetchProjectInfoConfig, FetchWorkItemConfig, GeneratePlanConfig, TechnicalPlanNodeConfig, VariableExtractorConfig, WaitFeishuFieldConfig } from './schemas'
import {
 aiAgentConfigSchema,
 aiCodeReviewConfigSchema,
 aiCodingConfigSchema,
 aiCodingDispatcherConfigSchema,
 aiPlanApprovalConfigSchema,
 aiPlanGenerationConfigSchema,
 aiPromptConfigSchema,
 aiVariableExtractorConfigSchema,
 contextRetrievalConfigSchema,
 createBranchConfigSchema,
 createPRConfigSchema,
 feishuEventTriggerConfigSchema,
 fetchProjectInfoConfigSchema,
 fetchWorkItemConfigSchema,
 generatePlanConfigSchema,
 technicalPlanNodeConfigSchema,
 variableExtractorConfigSchema,
 waitFeishuFieldConfigSchema,
} from './schemas'
// ============================================================================
// 类型定义
// ============================================================================
/** 节点分类 */
export type NodeCategory = 'trigger' | 'action' | 'control' | 'integration' | 'ai'
/** 节点类型定义 */
export interface NodeTypeDefinition<T = unknown> {
 /** 节点类型标识 */
 nodeType: string
 /** 显示名称 */
 displayName: string
 /** 描述 */
 description: string
 /** 图标 (iconify class) */
 icon: string
 /** 渐变色 (Tailwind classes) */
 color: string
 /** 分类 */
 category: NodeCategory
 /** Zod Schema */
 schema: ZodSchema<T>
 /** 默认配置 */
 defaultConfig: T
 /** 配置组件 (懒加载) */
 configComponent?: => Promise<{ default: Component }>
}
// ============================================================================
// 节点注册表
// ============================================================================
export const NODE_REGISTRY = {
 ai_prompt: {
 nodeType: 'ai_prompt',
 displayName: 'AI Prompt',
 description: '使用 AI 模型处理文本',
 icon: 'icon-[lucide--sparkles]',
 color: 'from-violet-500 to-purple-400',
 category: 'ai',
 schema: aiPromptConfigSchema,
 defaultConfig: aiPromptConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AIPromptConfig.vue'),
 } satisfies NodeTypeDefinition<AIPromptConfig>,
 ai_coding_dispatcher: {
 nodeType: 'ai_coding_dispatcher',
 displayName: 'AI 编码指派器',
 description: '分析需求并生成编码任务',
 icon: 'icon-[lucide--code-2]',
 color: 'from-blue-500 to-cyan-400',
 category: 'ai',
 schema: aiCodingDispatcherConfigSchema,
 defaultConfig: aiCodingDispatcherConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AICodingDispatcherConfig.vue'),
 } satisfies NodeTypeDefinition<AICodingDispatcherConfig>,
 fetch_work_item: {
 nodeType: 'fetch_work_item',
 displayName: '获取工作项',
 description: '从飞书获取工作项详情',
 icon: 'icon-[lucide--file-text]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: fetchWorkItemConfigSchema,
 defaultConfig: fetchWorkItemConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/FetchWorkItemConfig.vue'),
 } satisfies NodeTypeDefinition<FetchWorkItemConfig>,
 feishu_event_trigger: {
 nodeType: 'feishu_event_trigger',
 displayName: '飞书事件触发器',
 description: '监听飞书工作项事件',
 icon: 'icon-[lucide--zap]',
 color: 'from-amber-500 to-orange-400',
 category: 'trigger',
 schema: feishuEventTriggerConfigSchema,
 defaultConfig: feishuEventTriggerConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/FeishuEventTriggerConfig.vue'),
 } satisfies NodeTypeDefinition<FeishuEventTriggerConfig>,
 variable_extractor: {
 nodeType: 'variable_extractor',
 displayName: '变量提取',
 description: '从 JSON 数据中提取变量',
 icon: 'icon-[lucide--variable]',
 color: 'from-cyan-500 to-blue-400',
 category: 'action',
 schema: variableExtractorConfigSchema,
 defaultConfig: variableExtractorConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/VariableExtractorConfig.vue'),
 } satisfies NodeTypeDefinition<VariableExtractorConfig>,
 ai_variable_extractor: {
 nodeType: 'ai_variable_extractor',
 displayName: 'AI 变量提取',
 description: '使用 AI 从文本中智能提取变量',
 icon: 'icon-[lucide--sparkles]',
 color: 'from-violet-500 to-fuchsia-400',
 category: 'ai',
 schema: aiVariableExtractorConfigSchema,
 defaultConfig: aiVariableExtractorConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AIVariableExtractorConfig.vue'),
 } satisfies NodeTypeDefinition<AIVariableExtractorConfig>,
 context_retrieval: {
 nodeType: 'context_retrieval',
 displayName: '召回上下文',
 description: '从代码库检索相关代码片段',
 icon: 'icon-[lucide--search-code]',
 color: 'from-violet-500 to-purple-400',
 category: 'ai',
 schema: contextRetrievalConfigSchema,
 defaultConfig: contextRetrievalConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/ContextRetrievalConfig.vue'),
 } satisfies NodeTypeDefinition<ContextRetrievalConfig>,
 fetch_project_info: {
 nodeType: 'fetch_project_info',
 displayName: '获取项目信息',
 description: '获取项目配置和仓库列表',
 icon: 'icon-[lucide--folder-search]',
 color: 'from-amber-500 to-orange-400',
 category: 'integration',
 schema: fetchProjectInfoConfigSchema,
 defaultConfig: fetchProjectInfoConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/FetchProjectInfoConfig.vue'),
 } satisfies NodeTypeDefinition<FetchProjectInfoConfig>,
 wait_feishu_field: {
 nodeType: 'wait_feishu_field',
 displayName: '等待飞书字段',
 description: '等待飞书工作项字段满足条件',
 icon: 'icon-[lucide--clock]',
 color: 'from-amber-500 to-orange-400',
 category: 'control',
 schema: waitFeishuFieldConfigSchema,
 defaultConfig: waitFeishuFieldConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/WaitFeishuConfig.vue'),
 } satisfies NodeTypeDefinition<WaitFeishuFieldConfig>,
 ai_technical_plan: {
 nodeType: 'ai_technical_plan',
 displayName: 'AI 技术方案',
 description: '根据需求生成技术方案',
 icon: 'icon-[lucide--file-code]',
 color: 'from-emerald-500 to-teal-400',
 category: 'ai',
 schema: technicalPlanNodeConfigSchema,
 defaultConfig: technicalPlanNodeConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/TechnicalPlanConfig.vue'),
 } satisfies NodeTypeDefinition<TechnicalPlanNodeConfig>,
 create_branch: {
 nodeType: 'create_branch',
 displayName: '创建分支',
 description: '在 Git 仓库中创建新分支',
 icon: 'icon-[lucide--git-branch]',
 color: 'from-emerald-500 to-teal-400',
 category: 'action',
 schema: createBranchConfigSchema,
 defaultConfig: createBranchConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/CreateBranchConfig.vue'),
 } satisfies NodeTypeDefinition<CreateBranchConfig>,
 create_pr: {
 nodeType: 'create_pr',
 displayName: '创建 PR',
 description: '在 Git 仓库中创建 Pull Request',
 icon: 'icon-[lucide--git-pull-request]',
 color: 'from-violet-500 to-purple-400',
 category: 'action',
 schema: createPRConfigSchema,
 defaultConfig: createPRConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/CreatePRConfig.vue'),
 } satisfies NodeTypeDefinition<CreatePRConfig>,
 generate_plan: {
 nodeType: 'generate_plan',
 displayName: '生成方案',
 description: '根据需求生成开发计划',
 icon: 'icon-[lucide--list-todo]',
 color: 'from-amber-500 to-orange-400',
 category: 'ai',
 schema: generatePlanConfigSchema,
 defaultConfig: generatePlanConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/GeneratePlanConfig.vue'),
 } satisfies NodeTypeDefinition<GeneratePlanConfig>,
 ai_agent: {
 nodeType: 'ai_agent',
 displayName: 'Friday 编码助手',
 description: '自主编码的智能代理，可调用工具完成复杂任务',
 icon: 'icon-[lucide--brain-circuit]',
 color: 'from-blue-500 to-cyan-400',
 category: 'ai',
 schema: aiAgentConfigSchema,
 defaultConfig: aiAgentConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AIAgentConfig.vue'),
 } satisfies NodeTypeDefinition<AIAgentConfig>,
 ai_plan_generation: {
 nodeType: 'ai_plan_generation',
 displayName: 'AI 方案生成',
 description: 'AI 自动跨仓库分析需求，生成结构化技术方案',
 icon: 'icon-[lucide--file-text]',
 color: 'from-emerald-500 to-teal-400',
 category: 'ai',
 schema: aiPlanGenerationConfigSchema,
 defaultConfig: aiPlanGenerationConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AIPlanGenerationConfig.vue'),
 } satisfies NodeTypeDefinition<AIPlanGenerationConfig>,
 ai_plan_approval: {
 nodeType: 'ai_plan_approval',
 displayName: '方案审批',
 description: '审批技术方案，支持通过/驳回分支',
 icon: 'icon-[lucide--check-circle]',
 color: 'from-amber-500 to-orange-400',
 category: 'ai',
 schema: aiPlanApprovalConfigSchema,
 defaultConfig: aiPlanApprovalConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AIPlanApprovalConfig.vue'),
 } satisfies NodeTypeDefinition<AIPlanApprovalConfig>,
 ai_coding: {
 nodeType: 'ai_coding',
 displayName: 'AI 编码执行',
 description: 'AI 自动在容器中编码并创建 MR',
 icon: 'icon-[lucide--terminal]',
 color: 'from-blue-500 to-cyan-400',
 category: 'ai',
 schema: aiCodingConfigSchema,
 defaultConfig: aiCodingConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AICodingConfig.vue'),
 } satisfies NodeTypeDefinition<AICodingConfig>,
 ai_code_review: {
 nodeType: 'ai_code_review',
 displayName: 'AI 代码审查',
 description: 'AI 多维度代码审查，输出结构化审查报告',
 icon: 'icon-[lucide--search-code]',
 color: 'from-amber-500 to-orange-400',
 category: 'ai',
 schema: aiCodeReviewConfigSchema,
 defaultConfig: aiCodeReviewConfigSchema.parse({}),
 configComponent: => import('~/components/workflow/config/AICodeReviewConfig.vue'),
 } satisfies NodeTypeDefinition<AICodeReviewConfig>,
} as const
// ============================================================================
// 辅助类型与函数
// ============================================================================
/** 注册表中的节点类型键 */
export type NodeTypeKey = keyof typeof NODE_REGISTRY
/** 检查节点类型是否在注册表中 */
export function hasNodeDefinition(nodeType: string): nodeType is NodeTypeKey {
 return nodeType in NODE_REGISTRY
}
/** 获取节点定义 */
export function getNodeDefinition<K extends NodeTypeKey>(
 nodeType: K,
): (typeof NODE_REGISTRY)[K]
export function getNodeDefinition(nodeType: string): NodeTypeDefinition | undefined
export function getNodeDefinition(nodeType: string): NodeTypeDefinition | undefined {
 if (hasNodeDefinition(nodeType)) {
 return NODE_REGISTRY[nodeType]
 }
 return undefined
}
/** 获取节点默认配置 */
export function getDefaultConfig<K extends NodeTypeKey>(
 nodeType: K,
): (typeof NODE_REGISTRY)[K]['defaultConfig']
export function getDefaultConfig(nodeType: string): unknown
export function getDefaultConfig(nodeType: string): unknown {
 const def = getNodeDefinition(nodeType)
 return def?.defaultConfig
}
/** 按分类分组的节点定义 */
export function getNodesByCategory: Record<NodeCategory, NodeTypeDefinition> {
 const groups: Record<NodeCategory, NodeTypeDefinition> = {
 trigger:,
 action:,
 control:,
 integration:,
 ai:,
 }
 for (const def of Object.values(NODE_REGISTRY)) {
 groups[def.category].push(def)
 }
 return groups
}
/** 验证节点配置 */
export function validateNodeConfig(
 nodeType: string,
 config: unknown,
): { success: true, data: unknown } | { success: false, errors: Record<string, string> } {
 const def = getNodeDefinition(nodeType)
 if (!def) {
 return { success: false, errors: { _root: `未知节点类型: ${nodeType}` } }
 }
 const result = def.schema.safeParse(config)
 if (result.success) {
 return { success: true, data: result.data }
 }
 const errors: Record<string, string> = {}
 for (const issue of result.error.issues) {
 errors[issue.path.join('.')] = issue.message
 }
 return { success: false, errors }
}
