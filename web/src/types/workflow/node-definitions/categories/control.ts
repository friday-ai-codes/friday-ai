/**
 * Control 节点定义
 */
import { z } from 'zod'
import { createNodeDefinition } from '../index'
import type { NodeDefinition } from '../types'
// ============================================================================
// Delay
// ============================================================================
const delaySchema = z.object({
 delay_seconds: z.number.int.min(1).max(86400).default(60),
 delay_until: z.string.default(''),
})
export const delayDef = createNodeDefinition({
 nodeType: 'delay',
 displayName: '延迟',
 description: '暂停工作流执行指定时间',
 icon: 'icon-[lucide--clock]',
 color: 'from-amber-500 to-orange-400',
 category: 'control',
 schema: delaySchema,
 defaultConfig: delaySchema.parse({}),
 uiSchema: {
 groups: [{ key: 'timing', label: '时间设置', fields: ['delay_seconds', 'delay_until'] }],
 fields: {
 delay_seconds: { widget: 'number', help: '延迟执行的秒数 (1-86400)' },
 delay_until: { widget: 'text', help: 'ISO 格式时间字符串，优先于 delay_seconds' },
 },
 },
})
// ============================================================================
// Condition
// ============================================================================
const conditionExpressionSchema = z.object({
 field: z.string.default(''),
 operator: z.enum([
 'eq', 'ne', 'gt', 'gte', 'lt', 'lte',
 'contains', 'not_contains', 'starts_with', 'ends_with',
 'is_empty', 'is_not_empty', 'is_true', 'is_false',
 ]).default('eq'),
 value: z.unknown.default(''),
})
const conditionBranchSchema = z.object({
 name: z.string.default(''),
 expression: conditionExpressionSchema.default({ field: '', operator: 'eq' as const, value: '' }),
})
const conditionSchema = z.object({
 conditions: z.array(conditionBranchSchema).default,
 default_branch: z.string.default('else'),
})
export const conditionDef = createNodeDefinition({
 nodeType: 'condition',
 displayName: '条件分支',
 description: '根据条件判断走不同的分支',
 icon: 'icon-[lucide--git-branch]',
 color: 'from-amber-500 to-orange-400',
 category: 'control',
 schema: conditionSchema,
 defaultConfig: conditionSchema.parse({}),
 uiSchema: {
 fields: {
 conditions: { widget: 'json-editor', help: '条件列表，支持多分支' },
 default_branch: { widget: 'text', help: '当所有条件都不满足时走的分支' },
 },
 },
})
// ============================================================================
// Parallel
// ============================================================================
const parallelBranchSchema = z.object({
 name: z.string.default(''),
 enabled: z.boolean.default(true),
})
const parallelSchema = z.object({
 branches: z.array(parallelBranchSchema).default([
 { name: '分支 1', enabled: true },
 { name: '分支 2', enabled: true },
 ]),
 pass_input: z.boolean.default(true),
})
export const parallelDef = createNodeDefinition({
 nodeType: 'parallel',
 displayName: '并行分支',
 description: '将工作流分成多个并行分支',
 icon: 'icon-[lucide--git-fork]',
 color: 'from-amber-500 to-orange-400',
 category: 'control',
 schema: parallelSchema,
 defaultConfig: parallelSchema.parse({}),
 uiSchema: {
 fields: {
 branches: { widget: 'json-editor', help: '分支配置（名称和启用状态）' },
 pass_input: { widget: 'boolean', help: '是否将输入数据传递给所有分支' },
 },
 },
})
// ============================================================================
// Join
// ============================================================================
const joinSchema = z.object({
 wait_mode: z.enum(['all', 'any', 'count']).default('all'),
 wait_count: z.number.int.min(1).default(1),
 merge_strategy: z.enum(['array', 'object', 'first', 'last']).default('array'),
 timeout: z.number.int.min(0).default(0),
})
export const joinDef = createNodeDefinition({
 nodeType: 'join',
 displayName: '并行汇合',
 description: '等待所有并行分支完成后继续',
 icon: 'icon-[lucide--git-merge]',
 color: 'from-amber-500 to-orange-400',
 category: 'control',
 schema: joinSchema,
 defaultConfig: joinSchema.parse({}),
 uiSchema: {
 fields: {
 wait_mode: { widget: 'select', help: 'all=等待全部, any=任一完成, count=指定数量' },
 wait_count: { widget: 'number', help: 'wait_mode=count 时生效' },
 merge_strategy: { widget: 'select', help: '如何合并各分支的输出' },
 timeout: { widget: 'number', help: '等待超时时间（秒），0 表示不超时' },
 },
 },
})
// ============================================================================
// Human Approval
// ============================================================================
const humanApprovalSchema = z.object({
 approvers: z.array(z.string).default,
 approval_message: z.string.default(''),
 timeout_hours: z.number.int.min(1).default(72),
})
export const humanApprovalDef = createNodeDefinition({
 nodeType: 'human_approval',
 displayName: '人工审批',
 description: '等待人工审批',
 icon: 'icon-[lucide--user-check]',
 color: 'from-amber-500 to-orange-400',
 category: 'control',
 schema: humanApprovalSchema,
 defaultConfig: humanApprovalSchema.parse({}),
})
// ============================================================================
// Aggregated exports
// ============================================================================
export const CONTROL_DEFS: Record<string, NodeDefinition> = {
 delay: delayDef,
 condition: conditionDef,
 parallel: parallelDef,
 join: joinDef,
 human_approval: humanApprovalDef,
}
