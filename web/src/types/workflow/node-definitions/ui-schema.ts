/**
 * UiSchema 辅助函数
 *
 * 提供便捷的 UiSchema 构建工具。
 */
import type { UiSchema, UiSchemaField, UiSchemaGroup } from './types'
// 重新导出类型
export type { UiSchema, UiSchemaField, UiSchemaGroup, UiVisibleIf, UiWidget, UiConditionOperator } from './types'
/**
 * 构建 UiSchema 的辅助函数
 *
 * @param fieldConfigs 字段配置映射
 * @param groups 可选的字段分组
 * @returns 完整的 UiSchema
 *
 * @example
 * ```ts
 * const schema = buildUiSchema(
 * {
 * delay_seconds: { widget: 'number', help: '延迟秒数' },
 * delay_until: { widget: 'text', help: 'ISO 时间' },
 * },
 * [{ key: 'timing', label: '时间设置', fields: ['delay_seconds', 'delay_until'] }]
 * )
 * ```
 */
export function buildUiSchema(
 fieldConfigs: Record<string, UiSchemaField>,
 groups?: UiSchemaGroup,
): UiSchema {
 return {
 ...(groups ? { groups }: {}),
 fields: fieldConfigs,
 }
}
