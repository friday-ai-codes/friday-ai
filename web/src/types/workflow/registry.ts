import type { Component } from 'vue'
import type { ZodSchema } from 'zod'
import type { AICodingDispatcherConfig, AIPromptConfig, FeishuEventTriggerConfig, FetchWorkItemConfig } from './schemas'
import {
 aiCodingDispatcherConfigSchema,
 aiPromptConfigSchema,
 feishuEventTriggerConfigSchema,
 fetchWorkItemConfigSchema,
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
