import type { NodeDefinition } from '../types'
/**
 * Trigger 节点定义
 */
import { z } from 'zod'
import { createNodeDefinition } from '../index'

// ============================================================================
// Manual Trigger
// ============================================================================

const manualTriggerSchema = z.object({
  input_schema: z.record(z.string(), z.unknown()).default({}),
})

export const manualTriggerDef = createNodeDefinition({
  nodeType: 'manual_trigger',
  displayName: '手动触发',
  description: '手动触发工作流执行',
  icon: 'icon-[lucide--play]',
  color: 'from-emerald-500 to-teal-400',
  category: 'trigger',
  schema: manualTriggerSchema,
  defaultConfig: manualTriggerSchema.parse({}),
  uiSchema: {
    fields: {
      input_schema: {
        widget: 'json-editor',
        help: '定义用户触发时需要输入的参数',
      },
    },
  },
})

// ============================================================================
// Webhook Trigger
// ============================================================================

const webhookTriggerSchema = z.object({
  secret: z.string().default(''),
  method: z.enum(['POST', 'GET', 'PUT'], '请选择有效的选项').default('POST'),
})

export const webhookTriggerDef = createNodeDefinition({
  nodeType: 'webhook_trigger',
  displayName: 'Webhook',
  description: '通过 HTTP 请求触发',
  icon: 'icon-[lucide--webhook]',
  color: 'from-emerald-500 to-teal-400',
  category: 'trigger',
  schema: webhookTriggerSchema,
  defaultConfig: webhookTriggerSchema.parse({}),
})

// ============================================================================
// Feishu Event Trigger — 节点定义已由后端 /api/node-types/ 驱动（store 唯一运行时源）
// 此处不再声明；前端专属 configComponent 见 registry.ts CONFIG_COMPONENTS
// ============================================================================

// ============================================================================
// Aggregated exports (仅新增迁移的节点)
// ============================================================================

export const TRIGGER_DEFS: Record<string, NodeDefinition> = {
  manual_trigger: manualTriggerDef,
  webhook_trigger: webhookTriggerDef,
}
