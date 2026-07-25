import type { NodeDefinition } from '../types'
/**
 * Control 节点定义
 */
import { z } from 'zod'
import { createNodeDefinition } from '../index'

// ============================================================================
// Delay
// ============================================================================

const delaySchema = z.object({
  delay_seconds: z.number().int().min(1, '不能小于 1').max(86400, '不能大于 86400').default(60),
  delay_until: z.string().default(''),
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
  field: z.string().default(''),
  operator: z.enum([
    'eq',
    'ne',
    'gt',
    'gte',
    'lt',
    'lte',
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'is_empty',
    'is_not_empty',
    'is_true',
    'is_false',
  ], '请选择有效的选项').default('eq'),
  value: z.unknown().default(''),
})

const conditionBranchSchema = z.object({
  name: z.string().default(''),
  expression: conditionExpressionSchema.default({ field: '', operator: 'eq' as const, value: '' }),
})

const conditionSchema = z.object({
  conditions: z.array(conditionBranchSchema).default([]),
  default_branch: z.string().default('else'),
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
  name: z.string().default(''),
  enabled: z.boolean().default(true),
})

const parallelSchema = z.object({
  branches: z.array(parallelBranchSchema).default([
    { name: '分支 1', enabled: true },
    { name: '分支 2', enabled: true },
  ]),
  pass_input: z.boolean().default(true),
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
  wait_mode: z.enum(['all', 'any', 'count'], '请选择有效的选项').default('all'),
  wait_count: z.number().int().min(1, '不能小于 1').default(1),
  merge_strategy: z.enum(['array', 'object', 'first', 'last'], '请选择有效的选项').default('array'),
  timeout: z.number().int().min(0, '不能小于 0').default(0),
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
  // generic=通用控制台审批；plan_feishu=方案+飞书卡片审批（吸收原 ai_plan_approval）
  mode: z.enum(['generic', 'plan_feishu'], '请选择有效的选项').default('generic'),
  // plan_feishu 模式下推送审批卡片的飞书群 ID（留空则用上游传递的 chat_id）
  chat_id: z.string().default(''),
  approvers: z.array(z.string()).default([]),
  approval_message: z.string().default(''),
  timeout_hours: z.number().int().min(1, '不能小于 1').default(72),
})

export const humanApprovalDef = createNodeDefinition({
  nodeType: 'human_approval',
  displayName: '人工审批',
  description: '等待人工审批（支持方案+飞书卡片审批）',
  icon: 'icon-[lucide--user-check]',
  color: 'from-amber-500 to-orange-400',
  category: 'control',
  schema: humanApprovalSchema,
  defaultConfig: humanApprovalSchema.parse({}),
  uiSchema: {
    fields: {
      mode: { widget: 'select', help: 'generic=通用控制台审批；plan_feishu=方案+飞书卡片审批' },
      chat_id: { widget: 'text', help: 'plan_feishu 模式下发送审批卡片的飞书群 ID，留空则用上游传递的 chat_id' },
      approvers: { widget: 'json-editor', help: '审批人用户 ID 列表，为空则空间成员均可审批' },
      approval_message: { widget: 'textarea', help: '审批说明（可选）' },
      timeout_hours: { widget: 'number', help: '超时时间（小时）' },
    },
  },
})

// ============================================================================
// ForEach
// ============================================================================

const foreachSchema = z.object({
  list_source: z.string().default('{{input.items}}'),
  execution_mode: z.enum(['sequential', 'parallel'], '请选择有效的选项').default('sequential'),
  max_concurrency: z.number().int().min(1, '不能小于 1').max(50, '不能大于 50').default(5),
  on_iteration_error: z.enum(['abort', 'continue'], '请选择有效的选项').default('abort'),
})

export const foreachDef = createNodeDefinition({
  nodeType: 'foreach',
  displayName: 'ForEach 循环',
  // 迭代体尚未实现子 DAG 执行，元素原样透传；描述必须与后端 ForEachNode 一致，
  // 否则用户会以为拖上来就能对每个元素跑一段子流程。
  description: '把列表展开并汇总结果（迭代体透传元素，不执行子流程）',
  icon: 'icon-[lucide--repeat]',
  color: 'from-violet-500 to-purple-400',
  category: 'control',
  schema: foreachSchema,
  defaultConfig: foreachSchema.parse({}),
  uiSchema: {
    fields: {
      list_source: { widget: 'text', help: '列表来源，支持模板变量如 {{input.items}}' },
      execution_mode: { widget: 'select', help: 'sequential=串行, parallel=并发' },
      max_concurrency: { widget: 'number', help: '最大并发数（parallel 模式生效，1-50）' },
      on_iteration_error: { widget: 'select', help: 'abort=任一失败终止, continue=继续执行' },
    },
  },
})

// ============================================================================
// Variable Aggregate
// ============================================================================

const aggregateMappingSchema = z.object({
  source_node: z.string().default(''),
  output_field: z.string().default(''),
  target_key: z.string().default(''),
})

const aggregateSchema = z.object({
  mappings: z.array(aggregateMappingSchema).default([]),
})

export const aggregateDef = createNodeDefinition({
  nodeType: 'aggregate',
  displayName: '变量聚合',
  description: '将多个上游节点输出绑定为结构化变量',
  icon: 'icon-[lucide--combine]',
  color: 'from-violet-500 to-purple-400',
  category: 'control',
  schema: aggregateSchema,
  defaultConfig: aggregateSchema.parse({}),
  uiSchema: {
    fields: {
      mappings: { widget: 'json-editor', help: '聚合映射数组：source_node, output_field(可选), target_key' },
    },
  },
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
  foreach: foreachDef,
  aggregate: aggregateDef,
}
