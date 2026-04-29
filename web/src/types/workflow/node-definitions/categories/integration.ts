/**
 * Integration 节点定义
 */
import { z } from 'zod'
import { createNodeDefinition } from '../index'
import type { NodeDefinition } from '../types'
// ============================================================================
// Notify Feishu
// ============================================================================
const notifyFeishuSchema = z.object({
 webhook_url: z.string.default(''),
 message_type: z.enum(['text', 'post', 'interactive']).default('text'),
 content: z.string.default(''),
 title: z.string.default(''),
 at_all: z.boolean.default(false),
 at_users: z.array(z.string).default,
})
export const notifyFeishuDef = createNodeDefinition({
 nodeType: 'notify_feishu',
 displayName: '飞书通知',
 description: '发送消息到飞书',
 icon: 'icon-[lucide--message-square]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: notifyFeishuSchema,
 defaultConfig: notifyFeishuSchema.parse({}),
 uiSchema: {
 groups: [
 { key: 'message', label: '消息内容', fields: ['message_type', 'content', 'title'] },
 { key: 'target', label: '通知目标', fields: ['webhook_url', 'at_all', 'at_users'] },
 ],
 fields: {
 webhook_url: { widget: 'text', help: '飞书机器人 Webhook 地址' },
 message_type: { widget: 'select' },
 content: { widget: 'textarea', help: '消息内容，支持模板变量' },
 title: { widget: 'text', help: '富文本消息标题（仅 post 类型）', visible_if: { field: 'message_type', operator: 'eq', value: 'post' } },
 at_all: { widget: 'boolean', help: '@所有人' },
 at_users: { widget: 'json-editor', help: '@指定用户 ID 列表' },
 },
 },
})
// ============================================================================
// HTTP Request (简单占位，后续 Phase 迁移完善)
// ============================================================================
const httpRequestSchema = z.object({
 method: z.enum(['GET', 'POST', 'PUT', 'DELETE', 'PATCH']).default('GET'),
 url: z.string.default(''),
 headers: z.record(z.string, z.string).default({}),
 body: z.string.default(''),
 timeout: z.number.int.min(1).max(300).default(30),
})
export const httpRequestDef = createNodeDefinition({
 nodeType: 'http_request',
 displayName: 'HTTP 请求',
 description: '发送 HTTP 请求',
 icon: 'icon-[lucide--globe]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: httpRequestSchema,
 defaultConfig: httpRequestSchema.parse({}),
})
// ============================================================================
// Merge PR (简单占位)
// ============================================================================
const mergePRSchema = z.object({
 repositories: z.array(z.string).default,
 branch: z.string.default(''),
 delete_branch: z.boolean.default(true),
})
export const mergePRDef = createNodeDefinition({
 nodeType: 'merge_pr',
 displayName: '合并 PR',
 description: '合并 Pull Request',
 icon: 'icon-[lucide--git-merge]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: mergePRSchema,
 defaultConfig: mergePRSchema.parse({}),
})
// ============================================================================
// MCP Deploy (简单占位)
// ============================================================================
const mcpDeploySchema = z.object({
 service_name: z.string.default(''),
 config: z.record(z.string, z.unknown).default({}),
})
export const mcpDeployDef = createNodeDefinition({
 nodeType: 'mcp_deploy',
 displayName: 'MCP 部署',
 description: 'MCP 服务部署',
 icon: 'icon-[lucide--rocket]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: mcpDeploySchema,
 defaultConfig: mcpDeploySchema.parse({}),
})
// ============================================================================
// Feishu Chat Group nodes (简单占位)
// ============================================================================
const fetchGroupChatSchema = z.object({
 work_item_id: z.string.default(''),
})
export const fetchGroupChatDef = createNodeDefinition({
 nodeType: 'fetch_group_chat',
 displayName: '获取群聊',
 description: '从飞书工作项获取群聊 ID',
 icon: 'icon-[lucide--message-circle]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: fetchGroupChatSchema,
 defaultConfig: fetchGroupChatSchema.parse({}),
})
const joinGroupChatSchema = z.object({
 chat_id: z.string.default(''),
})
export const joinGroupChatDef = createNodeDefinition({
 nodeType: 'join_group_chat',
 displayName: '加入群聊',
 description: 'Bot 加入目标群聊',
 icon: 'icon-[lucide--user-plus]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: joinGroupChatSchema,
 defaultConfig: joinGroupChatSchema.parse({}),
})
const groupChatQuestionSchema = z.object({
 chat_id: z.string.default(''),
 question: z.string.default(''),
 timeout_seconds: z.number.int.default(300),
})
export const groupChatQuestionDef = createNodeDefinition({
 nodeType: 'group_chat_question',
 displayName: '群聊提问',
 description: '向群聊发送提问卡片等待回答',
 icon: 'icon-[lucide--message-circle-question]',
 color: 'from-emerald-500 to-teal-400',
 category: 'integration',
 schema: groupChatQuestionSchema,
 defaultConfig: groupChatQuestionSchema.parse({}),
})
// ============================================================================
// Aggregated exports
// ============================================================================
export const INTEGRATION_DEFS: Record<string, NodeDefinition> = {
 notify_feishu: notifyFeishuDef,
 http_request: httpRequestDef,
 merge_pr: mergePRDef,
 mcp_deploy: mcpDeployDef,
 fetch_group_chat: fetchGroupChatDef,
 join_group_chat: joinGroupChatDef,
 group_chat_question: groupChatQuestionDef,
}
