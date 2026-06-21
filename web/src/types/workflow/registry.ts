import type { Component } from 'vue'
import type { ZodSchema } from 'zod'
import type { UiSchema } from './node-definitions/types'
import type { NodeType } from '~/stores/useNodeTypesStore'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'

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
