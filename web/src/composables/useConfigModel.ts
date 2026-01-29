import type { ComputedRef, WritableComputedRef } from 'vue'
import type { ZodSchema } from 'zod'
import { computed } from 'vue'
// ============================================================================
// 类型定义
// ============================================================================
export interface UseConfigModelOptions<T> {
 /** 获取当前配置的函数 */
 config: => T
 /** 更新配置的函数 */
 emit: (value: T) => void
 /** 可选的 Zod schema 用于验证 */
 schema?: ZodSchema<T>
}
export interface UseConfigModelReturn<T> {
 /** 创建单个字段的双向绑定 */
 field: <K extends keyof T>(key: K, defaultValue?: T[K]) => WritableComputedRef<T[K]>
 /** 创建数组字段的操作方法 */
 arrayField: <K extends keyof T>(
 key: K,
 defaultValue?: T[K],
 ) => {
 value: ComputedRef<T[K]>
 includes: (item: T[K] extends (infer U) ? U: never) => boolean
 toggle: (item: T[K] extends (infer U) ? U: never, checked: boolean) => void
 }
 /** 批量更新多个字段 */
 updateFields: (updates: Partial<T>) => void
 /** 验证当前配置 */
 validate: => { success: boolean, errors?: Record<string, string> }
}
// ============================================================================
// Composable 实现
// ============================================================================
/**
 * 类型安全的配置模型代理
 *
 * @example
 * ```ts
 * const { field, arrayField } = useConfigModel({
 * config: => props.config,
 * emit: (v) => emit('update:config', v),
 * schema: aiPromptConfigSchema,
 * })
 *
 * // 简单字段
 * const model = field('model', 'claude-3-5-sonnet-20241022')
 *
 * // 数组字段 (checkbox group)
 * const eventTypes = arrayField('event_types', )
 * eventTypes.toggle('WorkitemCreateEvent', true)
 * ```
 */
export function useConfigModel<T extends Record<string, unknown>>(
 options: UseConfigModelOptions<T>,
): UseConfigModelReturn<T> {
 const { config, emit, schema } = options
 /**
 * 创建单个字段的双向绑定 computed
 */
 function field<K extends keyof T>(
 key: K,
 defaultValue?: T[K],
 ): WritableComputedRef<T[K]> {
 return computed({
 get: => {
 const current = config
 const value = current[key]
 return value !== undefined ? value: (defaultValue as T[K])
 },
 set: (value: T[K]) => {
 emit({ ...config, [key]: value })
 },
 })
 }
 /**
 * 创建数组字段的操作方法
 * 适用于 checkbox group 等场景
 */
 function arrayField<K extends keyof T>(
 key: K,
 defaultValue: T[K] = as T[K],
 ) {
 type ArrayItem = T[K] extends (infer U) ? U: never
 const value = computed( => {
 const current = config[key]
 return current !== undefined ? current: defaultValue
 })
 const includes = (item: ArrayItem): boolean => {
 const arr = value.value
 return Array.isArray(arr) && arr.includes(item)
 }
 const toggle = (item: ArrayItem, checked: boolean) => {
 const current = [...((config[key] as ArrayItem) || )]
 const index = current.indexOf(item)
 if (checked && index === -1) {
 current.push(item)
 }
 else if (!checked && index !== -1) {
 current.splice(index, 1)
 }
 emit({ ...config, [key]: current as T[K] })
 }
 return { value, includes, toggle }
 }
 /**
 * 批量更新多个字段
 */
 function updateFields(updates: Partial<T>) {
 emit({ ...config, ...updates })
 }
 /**
 * 验证当前配置
 */
 function validate: { success: boolean, errors?: Record<string, string> } {
 if (!schema) {
 return { success: true }
 }
 const result = schema.safeParse(config)
 if (result.success) {
 return { success: true }
 }
 const errors: Record<string, string> = {}
 for (const issue of result.error.issues) {
 const path = issue.path.join('.')
 errors[path] = issue.message
 }
 return { success: false, errors }
 }
 return {
 field,
 arrayField,
 updateFields,
 validate,
 }
}
