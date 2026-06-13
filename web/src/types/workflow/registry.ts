import type { Component } from 'vue'
import type { ZodSchema } from 'zod'
import type { NodeType } from '~/stores/useNodeTypesStore'
import type { UiSchema } from './node-definitions/types'
import type { AICodeReviewConfig, AICodingConfig, AICodingDispatcherConfig, AIPlanApprovalConfig, AIPlanGenerationConfig, AIPromptConfig, AIVariableExtractorConfig, ContextRetrievalConfig, CreateBranchConfig, CreatePRConfig, DeliveryKnowledgeSearchConfig, FeishuEventTriggerConfig, FetchSpaceInfoConfig, FetchWorkItemConfig, VariableExtractorConfig, WaitFeishuFieldConfig } from './schemas'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { ALL_NODE_DEFINITIONS } from './node-definitions/index'
import {
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
  deliveryKnowledgeSearchConfigSchema,
  feishuEventTriggerConfigSchema,
  fetchSpaceInfoConfigSchema,
  fetchWorkItemConfigSchema,
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
  /** Zod Schema（legacy 节点专属；store 适配器不再产出，故可选） */
  schema?: ZodSchema<T>
  /** 默认配置 */
  defaultConfig: T
  /** 声明式 UI Schema（可选，用于自动生成配置表单） */
  uiSchema?: UiSchema
  /** 配置组件 (懒加载) */
  configComponent?: () => Promise<{ default: Component }>
}

// ============================================================================
// 节点注册表
// ============================================================================

/**
 * 从 ALL_NODE_DEFINITIONS 适配为 NODE_REGISTRY 格式
 *
 * : 已迁移的 14 个节点从此处注入。
 * 剩余 AI 节点仍在下方硬编码（legacy）。
 */
const MIGRATED_REGISTRY = Object.fromEntries(
  Object.entries(ALL_NODE_DEFINITIONS).map(([key, def]) => [key, {
    nodeType: def.nodeType,
    displayName: def.displayName,
    description: def.description,
    icon: def.icon,
    color: def.color,
    category: def.category,
    schema: def.schema,
    defaultConfig: def.defaultConfig,
    uiSchema: def.uiSchema,
  } satisfies NodeTypeDefinition]),
) as Record<string, NodeTypeDefinition>

export const NODE_REGISTRY = {
  // --- 已迁移节点 (从 node-definitions 自动生成) ---
  ...MIGRATED_REGISTRY,

  // --- Legacy 节点 (后续 Phase 迁移) ---

  ai_prompt: {
    nodeType: 'ai_prompt',
    displayName: 'AI Prompt',
    description: '使用 AI 模型处理文本',
    icon: 'icon-[lucide--sparkles]',
    color: 'from-violet-500 to-purple-400',
    category: 'ai',
    schema: aiPromptConfigSchema,
    defaultConfig: aiPromptConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/AIPromptConfig.vue'),
  } satisfies NodeTypeDefinition<AIPromptConfig>,

  ai_coding_dispatcher: {
    nodeType: 'ai_coding_dispatcher',
    displayName: 'AI 编码指派',
    description: '分析需求并生成编码任务',
    icon: 'icon-[lucide--code-2]',
    color: 'from-teal-500 to-cyan-400',
    category: 'ai',
    schema: aiCodingDispatcherConfigSchema,
    defaultConfig: aiCodingDispatcherConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/AICodingDispatcherConfig.vue'),
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
    configComponent: () => import('~/components/workflow/config/FetchWorkItemConfig.vue'),
  } satisfies NodeTypeDefinition<FetchWorkItemConfig>,

  feishu_event_trigger: {
    nodeType: 'feishu_event_trigger',
    displayName: '飞书事件',
    description: '监听飞书工作项事件',
    icon: 'icon-[lucide--zap]',
    color: 'from-amber-500 to-orange-400',
    category: 'trigger',
    schema: feishuEventTriggerConfigSchema,
    defaultConfig: feishuEventTriggerConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/FeishuEventTriggerConfig.vue'),
  } satisfies NodeTypeDefinition<FeishuEventTriggerConfig>,

  variable_extractor: {
    nodeType: 'variable_extractor',
    displayName: '变量提取',
    description: '从 JSON 数据中提取变量',
    icon: 'icon-[lucide--variable]',
    color: 'from-teal-500 to-cyan-400',
    category: 'action',
    schema: variableExtractorConfigSchema,
    defaultConfig: variableExtractorConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/VariableExtractorConfig.vue'),
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
    configComponent: () => import('~/components/workflow/config/AIVariableExtractorConfig.vue'),
  } satisfies NodeTypeDefinition<AIVariableExtractorConfig>,

  context_retrieval: {
    nodeType: 'context_retrieval',
    displayName: '上下文检索',
    description: '从代码库检索相关代码片段',
    icon: 'icon-[lucide--search-code]',
    color: 'from-violet-500 to-purple-400',
    category: 'ai',
    schema: contextRetrievalConfigSchema,
    defaultConfig: contextRetrievalConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/ContextRetrievalConfig.vue'),
  } satisfies NodeTypeDefinition<ContextRetrievalConfig>,

  delivery_knowledge_search: {
    nodeType: 'delivery_knowledge_search',
    displayName: '交付知识检索',
    description: '检索相似历史交付并注入上下文',
    icon: 'icon-[lucide--search]',
    color: 'from-teal-500 to-emerald-400',
    category: 'ai',
    schema: deliveryKnowledgeSearchConfigSchema,
    defaultConfig: deliveryKnowledgeSearchConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/DeliveryKnowledgeSearchConfig.vue'),
  } satisfies NodeTypeDefinition<DeliveryKnowledgeSearchConfig>,

  fetch_project_info: {
    nodeType: 'fetch_project_info',
    displayName: '获取项目信息',
    description: '获取项目配置和仓库列表',
    icon: 'icon-[lucide--folder-search]',
    color: 'from-amber-500 to-orange-400',
    category: 'integration',
    schema: fetchSpaceInfoConfigSchema,
    defaultConfig: fetchSpaceInfoConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/FetchProjectInfoConfig.vue'),
  } satisfies NodeTypeDefinition<FetchSpaceInfoConfig>,

  wait_feishu_field: {
    nodeType: 'wait_feishu_field',
    displayName: '等待飞书',
    description: '等待飞书工作项字段满足条件',
    icon: 'icon-[lucide--clock]',
    color: 'from-amber-500 to-orange-400',
    category: 'control',
    schema: waitFeishuFieldConfigSchema,
    defaultConfig: waitFeishuFieldConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/WaitFeishuConfig.vue'),
  } satisfies NodeTypeDefinition<WaitFeishuFieldConfig>,

  create_branch: {
    nodeType: 'create_branch',
    displayName: '创建分支',
    description: '在 Git 仓库中创建新分支',
    icon: 'icon-[lucide--git-branch]',
    color: 'from-emerald-500 to-teal-400',
    category: 'action',
    schema: createBranchConfigSchema,
    defaultConfig: createBranchConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/CreateBranchConfig.vue'),
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
    configComponent: () => import('~/components/workflow/config/CreatePRConfig.vue'),
  } satisfies NodeTypeDefinition<CreatePRConfig>,

  ai_plan_generation: {
    nodeType: 'ai_plan_generation',
    displayName: 'AI 方案生成',
    description: 'AI 自动跨仓库分析需求，生成结构化技术方案',
    icon: 'icon-[lucide--file-text]',
    color: 'from-emerald-500 to-teal-400',
    category: 'ai',
    schema: aiPlanGenerationConfigSchema,
    defaultConfig: aiPlanGenerationConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/AIPlanGenerationConfig.vue'),
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
    configComponent: () => import('~/components/workflow/config/AIPlanApprovalConfig.vue'),
  } satisfies NodeTypeDefinition<AIPlanApprovalConfig>,

  ai_coding: {
    nodeType: 'ai_coding',
    displayName: 'AI 编码执行',
    description: 'AI 自动在容器中编码并创建 MR',
    icon: 'icon-[lucide--terminal]',
    color: 'from-teal-500 to-cyan-400',
    category: 'ai',
    schema: aiCodingConfigSchema,
    defaultConfig: aiCodingConfigSchema.parse({}),
    configComponent: () => import('~/components/workflow/config/AICodingConfig.vue'),
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
    configComponent: () => import('~/components/workflow/config/AICodeReviewConfig.vue'),
  } satisfies NodeTypeDefinition<AICodeReviewConfig>,
} as const

// ============================================================================
// 前端专属映射（API 不可下发，禁删）
// ============================================================================

/**
 * 节点配置面板的懒加载组件映射（前端专属）。
 *
 * Vue 组件无法被后端序列化下发，必须留在前端。`toDefinition` 适配器
 * 按 node_type 注入对应组件；无映射的节点走 uiSchema 声明式渲染。
 * 注意：`fetch_space_info` 复用既有 `FetchProjectInfoConfig.vue`（文件名保留，D-03）。
 */
export const CONFIG_COMPONENTS: Record<string, () => Promise<{ default: Component }>> = {
  ai_prompt: () => import('~/components/workflow/config/AIPromptConfig.vue'),
  ai_coding_dispatcher: () => import('~/components/workflow/config/AICodingDispatcherConfig.vue'),
  fetch_work_item: () => import('~/components/workflow/config/FetchWorkItemConfig.vue'),
  feishu_event_trigger: () => import('~/components/workflow/config/FeishuEventTriggerConfig.vue'),
  variable_extractor: () => import('~/components/workflow/config/VariableExtractorConfig.vue'),
  ai_variable_extractor: () => import('~/components/workflow/config/AIVariableExtractorConfig.vue'),
  context_retrieval: () => import('~/components/workflow/config/ContextRetrievalConfig.vue'),
  delivery_knowledge_search: () => import('~/components/workflow/config/DeliveryKnowledgeSearchConfig.vue'),
  fetch_space_info: () => import('~/components/workflow/config/FetchProjectInfoConfig.vue'),
  wait_feishu_field: () => import('~/components/workflow/config/WaitFeishuConfig.vue'),
  create_branch: () => import('~/components/workflow/config/CreateBranchConfig.vue'),
  create_pr: () => import('~/components/workflow/config/CreatePRConfig.vue'),
  ai_plan_generation: () => import('~/components/workflow/config/AIPlanGenerationConfig.vue'),
  ai_plan_approval: () => import('~/components/workflow/config/AIPlanApprovalConfig.vue'),
  ai_coding: () => import('~/components/workflow/config/AICodingConfig.vue'),
  ai_code_review: () => import('~/components/workflow/config/AICodeReviewConfig.vue'),
}

// ============================================================================
// store 适配器与辅助函数（唯一运行时源 = useNodeTypesStore）
// ============================================================================

/** 注册表中的节点类型键（store 驱动后退化为字符串别名） */
export type NodeTypeKey = string

/**
 * 把后端下发的 store NodeType 适配为前端 NodeTypeDefinition 形态（snake→camel）。
 *
 * - `color` 后端不产出 → 取 nodeVisuals（前端视觉唯一源）
 * - `defaultConfig` 直接用后端 default_config，免 zod.parse({})
 * - `configComponent` 来自前端专属 CONFIG_COMPONENTS 映射
 */
function toDefinition(nt: NodeType): NodeTypeDefinition {
  return {
    nodeType: nt.node_type,
    displayName: nt.display_name,
    description: nt.description,
    icon: nt.icon,
    color: getNodeVisual(nt.node_type).color,
    category: nt.category,
    defaultConfig: nt.default_config ?? {},
    uiSchema: (nt.ui_schema ?? undefined) as UiSchema | undefined,
    configComponent: CONFIG_COMPONENTS[nt.node_type],
  }
}

/** 检查节点类型是否存在于运行时 store */
export function hasNodeDefinition(nodeType: string): boolean {
  return useNodeTypesStore().getNodeType(nodeType) !== undefined
}

/** 获取节点定义（store 适配，未就绪/未知返回 undefined） */
export function getNodeDefinition(nodeType: string): NodeTypeDefinition | undefined {
  const nt = useNodeTypesStore().getNodeType(nodeType)
  return nt ? toDefinition(nt) : undefined
}

/** 获取节点默认配置（来自后端 default_config） */
export function getDefaultConfig(nodeType: string): unknown {
  return getNodeDefinition(nodeType)?.defaultConfig
}

/** 按分类分组的节点定义（从 store nodeTypesByCategory 派生） */
export function getNodesByCategory(): Record<NodeCategory, NodeTypeDefinition[]> {
  const byCategory = useNodeTypesStore().nodeTypesByCategory
  const groups: Record<NodeCategory, NodeTypeDefinition[]> = {
    trigger: [],
    action: [],
    control: [],
    integration: [],
    ai: [],
  }

  for (const category of Object.keys(groups) as NodeCategory[]) {
    groups[category] = (byCategory[category] ?? []).map(toDefinition)
  }

  return groups
}

/** JSON Schema 顶层类型轻量匹配（不引入 ajv） */
function matchesJsonSchemaType(value: unknown, type: string): boolean {
  switch (type) {
    case 'string':
      return typeof value === 'string'
    case 'number':
      return typeof value === 'number'
    case 'integer':
      return typeof value === 'number' && Number.isInteger(value)
    case 'boolean':
      return typeof value === 'boolean'
    case 'array':
      return Array.isArray(value)
    case 'object':
      return typeof value === 'object' && value !== null && !Array.isArray(value)
    case 'null':
      return value === null
    default:
      return true
  }
}

/**
 * 验证节点配置（轻量降级版，Pitfall 5）。
 *
 * 仅基于后端 `config_schema.required` 校验必填、`properties.*.type` 校验顶层类型；
 * 完整校验交 Phase 20 后端统一 `WorkflowGraphValidator`（VAL-01/02），本阶段不引入 ajv。
 */
export function validateNodeConfig(
  nodeType: string,
  config: unknown,
): { success: true, data: unknown } | { success: false, errors: Record<string, string> } {
  const nt = useNodeTypesStore().getNodeType(nodeType)
  if (!nt) {
    return { success: false, errors: { _root: `未知节点类型: ${nodeType}` } }
  }

  const schema = (nt.config_schema ?? {}) as Record<string, any>
  const required: string[] = Array.isArray(schema.required) ? schema.required : []
  const properties: Record<string, any> = (schema.properties ?? {}) as Record<string, any>
  const cfg = (config ?? {}) as Record<string, unknown>
  const errors: Record<string, string> = {}

  for (const key of required) {
    const value = cfg[key]
    if (value === undefined || value === null || value === '') {
      errors[key] = '此字段为必填项'
    }
  }

  for (const [key, prop] of Object.entries(properties)) {
    const value = cfg[key]
    if (value === undefined || value === null) {
      continue
    }
    const expected = prop?.type
    if (typeof expected === 'string' && !matchesJsonSchemaType(value, expected)) {
      errors[key] = `类型应为 ${expected}`
    }
  }

  if (Object.keys(errors).length > 0) {
    return { success: false, errors }
  }
  return { success: true, data: config }
}
