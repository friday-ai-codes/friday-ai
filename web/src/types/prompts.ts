/**
 * Prompt 类型定义 —— zod schema 驱动，单一事实来源。
 *
 * 字段名严格 snake_case，与后端 server/prompts/serializers.py 对齐。
 *
 * 同步约束：本文件字段来源于
 * - server/prompts/serializers.py（6 个 Serializer.Meta.fields）
 * - server/prompts/models.py（PromptCategory / PromptScope TextChoices）
 * 后端字段名或枚举值变更必须同步此文件。
 */

import { z } from 'zod'

// ============================================================================
// 枚举（与 server/prompts/models.py::PromptCategory / PromptScope 对齐）
// ============================================================================

export const PromptCategorySchema = z.enum([
  'ai_node',
  'chat_agent',
  'aux_model',
  'feishu_bot',
  'repo_summary',
])
export type PromptCategory = z.infer<typeof PromptCategorySchema>

export const PromptScopeSchema = z.enum(['system', 'project'])
export type PromptScope = z.infer<typeof PromptScopeSchema>

// ============================================================================
// 变量元数据（variables_schema 的值类型）
// ============================================================================

export const VariableSpecSchema = z.object({
  type: z.enum(['str', 'int', 'bool', 'float']).optional(),
  required: z.boolean().optional(),
  description: z.string().optional(),
  default: z.string().optional(),
})
export type VariableSpec = z.infer<typeof VariableSpecSchema>

// ============================================================================
// PromptVersion（server/prompts/serializers.py::PromptVersionSerializer 对齐）
// ============================================================================

export const PromptVersionSchema = z.object({
  id: z.string().uuid(),
  version: z.number().int(),
  body: z.string(),
  variables_schema: z.record(z.string(), VariableSpecSchema).default({}),
  declared_variables: z.array(z.string()),
  change_note: z.string(),
  created_by: z.number().int().nullable(),
  created_at: z.string(), // ISO datetime
})
export type PromptVersion = z.infer<typeof PromptVersionSchema>

// ============================================================================
// PromptListItem（server/prompts/serializers.py::PromptListSerializer 对齐）
// ============================================================================

export const PromptListItemSchema = z.object({
  id: z.string().uuid(),
  slug: z.string(),
  category: PromptCategorySchema,
  scope: PromptScopeSchema,
  project: z.string().uuid().nullable(),
  title: z.string(),
  description: z.string(),
  is_builtin: z.boolean(),
  active_version_number: z.number().int().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type PromptListItem = z.infer<typeof PromptListItemSchema>

// ============================================================================
// PromptDetail（server/prompts/serializers.py::PromptDetailSerializer 对齐）
// ============================================================================

export const PromptDetailSchema = z.object({
  id: z.string().uuid(),
  slug: z.string(),
  category: PromptCategorySchema,
  scope: PromptScopeSchema,
  project: z.string().uuid().nullable(),
  title: z.string(),
  description: z.string(),
  is_builtin: z.boolean(),
  active_version: PromptVersionSchema.nullable(),
  declared_variables: z.array(z.string()),
  created_by: z.number().int().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type PromptDetail = z.infer<typeof PromptDetailSchema>

// ============================================================================
// 创建/更新请求 payload
// （server/prompts/serializers.py::PromptCreateSerializer / PromptUpdateSerializer 对齐）
// ============================================================================

export const PromptCreateInputSchema = z.object({
  slug: z.string().min(1),
  category: PromptCategorySchema,
  scope: PromptScopeSchema,
  project: z.string().uuid().nullable().optional(),
  title: z.string().min(1).max(200),
  description: z.string().max(1000).optional().default(''),
  body: z.string().min(1).max(32768),
  variables_schema: z.record(z.string(), VariableSpecSchema).optional().default({}),
  change_note: z.string().max(500).optional().default(''),
})
export type PromptCreateInput = z.infer<typeof PromptCreateInputSchema>

export const PromptUpdateInputSchema = z.object({
  title: z.string().min(1).max(200).optional(),
  description: z.string().max(1000).optional(),
  body: z.string().min(1).max(32768).optional(),
  variables_schema: z.record(z.string(), VariableSpecSchema).optional(),
  change_note: z.string().max(500).optional(),
})
export type PromptUpdateInput = z.infer<typeof PromptUpdateInputSchema>

// ============================================================================
// 422 响应 missing 变量错误（对应 fixture prompt-preview-error.json）
// Source: server/prompts/views.py:65-75 _handle_prompt_error
// ============================================================================

export interface PromptVariableMissingPayload {
  error: 'prompt_variable_missing'
  slug: string
  missing: string[]
}
