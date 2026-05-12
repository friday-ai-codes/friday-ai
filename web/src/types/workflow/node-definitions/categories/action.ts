import type { NodeDefinition } from '../types'
/**
 * Action 节点定义
 */
import { z } from 'zod'
import { createNodeDefinition } from '../index'
// ============================================================================
// Code
// ============================================================================
const codeSchema = z.object({
 code: z.string.default('# 编写 Python 代码\n# 通过 context["output"] = {...} 设置输出\n'),
 timeout_seconds: z.number.int.min(1).max(300).default(30),
})
export const codeDef = createNodeDefinition({
 nodeType: 'code',
 displayName: '代码执行',
 description: '执行 Python 代码片段',
 icon: 'icon-[lucide--code]',
 color: 'from-emerald-500 to-green-400',
 category: 'action',
 schema: codeSchema,
 defaultConfig: codeSchema.parse({}),
 uiSchema: {
 fields: {
 code: { widget: 'json-editor', help: 'Python 代码片段，通过 context["output"] = {...} 设置输出' },
 timeout_seconds: { widget: 'number', help: '执行超时时间（秒，1-300）' },
 },
 },
})
// ============================================================================
// Aggregated exports
// ============================================================================
export const ACTION_DEFS: Record<string, NodeDefinition> = {
 code: codeDef,
}
