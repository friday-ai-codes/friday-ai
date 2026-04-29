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
// 节点定义（后续 task 会从 categories/ 导入并聚合）
// PLACEHOLDER_FOR_CATEGORY_IMPORTS
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
 * 所有节点定义的聚合映射
 *
 * 后续 task 会从此导出已迁移节点的定义。
 * 当前为空，task 2 填充。
 */
export const ALL_NODE_DEFINITIONS: Record<string, NodeDefinition> = {}
/**
 * 获取指定节点的定义
 */
export function getNodeDef(nodeType: string): NodeDefinition | undefined {
 return ALL_NODE_DEFINITIONS[nodeType]
}
