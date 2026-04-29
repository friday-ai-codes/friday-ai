/**
 * node-definitions — 统一 NodeDefinition 契约
 *
 * 前后端共享的节点定义单一 source of truth。
 * 前端直接 import 类型和定义，后端通过构建脚本生成 JSON 消费。
 *
 * 使用方式：
 * - 类型: import { NodeDefinition, UiSchema } from './node-definitions'
 * - 定义: import { ALL_NODE_DEFINITIONS, getNodeDef } from './node-definitions'
 * - 构建: import { buildUiSchema } from './node-definitions'
 */
// 类型导出
export type {
 NodeCategory,
 NodeDefinition,
 UiConditionOperator,
 UiSchema,
 UiSchemaField,
 UiSchemaGroup,
 UiVisibleIf,
 UiWidget,
} from './types'
// 辅助函数
export { buildUiSchema } from './ui-schema'
// Category 导入
import { TRIGGER_DEFS } from './categories/trigger'
import { CONTROL_DEFS } from './categories/control'
import { INTEGRATION_DEFS } from './categories/integration'
/**
 * 创建 NodeDefinition 的辅助函数
 *
 * identity function，用于类型推导。
 *
 * @example
 * ```ts
 * const delayDef = createNodeDefinition({
 * nodeType: 'delay',
 * displayName: '延迟',
 * // ...
 * })
 * ```
 */
import type { NodeDefinition } from './types'
export function createNodeDefinition<T>(def: NodeDefinition<T>): NodeDefinition<T> {
 return def
}
/**
 * 所有已迁移节点定义的聚合映射
 *
 * Phase 首批迁移 14 个节点（trigger/control/integration 三个 category）。
 * 剩余 AI 节点在后续 Phase 迁移，仍由 NODE_REGISTRY legacy 管理。
 */
export const ALL_NODE_DEFINITIONS: Record<string, NodeDefinition> = {
 ...TRIGGER_DEFS,
 ...CONTROL_DEFS,
 ...INTEGRATION_DEFS,
}
/**
 * 获取指定节点的定义
 */
export function getNodeDef(nodeType: string): NodeDefinition | undefined {
 return ALL_NODE_DEFINITIONS[nodeType]
}
