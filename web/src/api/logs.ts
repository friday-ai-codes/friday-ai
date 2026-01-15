/**
 * 日志 API - Webhook 和工作项日志
 */
import { del, get, post } from './client'
// ============ 类型定义 ============
/**
 * Webhook 日志状态
 */
export type WebhookLogStatus = 'accepted' | 'ignored' | 'error' | 'duplicate'
/**
 * Webhook 日志
 */
export interface WebhookLog {
 id: string
 event_uuid: string | null
 event_type: string
 project_key: string | null
 raw_request: string
 status: WebhookLogStatus
 error_message: string | null
 project_id: string | null
 created_at: string
}
/**
 * Webhook 日志详情（包含解析后的 JSON）
 */
export interface WebhookLogDetail extends WebhookLog {
 raw_request_parsed: Record<string, unknown> | null
}
/**
 * 工作项日志
 */
export interface WorkItemLog {
 id: string
 work_item_id: string
 work_item_type: string
 project_key: string
 raw_response: string
 project_id: string
 task_id: string | null
 created_at: string
}
/**
 * 工作项日志详情（包含解析后的 JSON）
 */
export interface WorkItemLogDetail extends WorkItemLog {
 raw_response_parsed: Record<string, unknown> | null
}
/**
 * 日志列表响应
 */
export interface LogListResponse<T> {
 items: T
 total: number
}
/**
 * Webhook 日志查询参数
 */
export interface WebhookLogQuery {
 project_id?: string
 event_type?: string
 status?: WebhookLogStatus
 start_date?: string
 end_date?: string
 limit?: number
 offset?: number
}
/**
 * 工作项日志查询参数
 */
export interface WorkItemLogQuery {
 project_id?: string
 task_id?: string
 work_item_id?: string
 start_date?: string
 end_date?: string
 limit?: number
 offset?: number
}
// ============ API 方法 ============
/**
 * 获取 Webhook 日志列表
 */
export async function listWebhookLogs(
 query: WebhookLogQuery = {},
): Promise<LogListResponse<WebhookLog>> {
 return get<LogListResponse<WebhookLog>>('/logs/webhooks', query as Record<string, string | number | undefined>)
}
/**
 * 获取 Webhook 日志详情
 */
export async function getWebhookLog(logId: string): Promise<WebhookLogDetail> {
 return get<WebhookLogDetail>(`/logs/webhooks/${logId}`)
}
/**
 * 获取工作项日志列表
 */
export async function listWorkItemLogs(
 query: WorkItemLogQuery = {},
): Promise<LogListResponse<WorkItemLog>> {
 return get<LogListResponse<WorkItemLog>>('/logs/work-items', query as Record<string, string | number | undefined>)
}
/**
 * 获取工作项日志详情
 */
export async function getWorkItemLog(logId: string): Promise<WorkItemLogDetail> {
 return get<WorkItemLogDetail>(`/logs/work-items/${logId}`)
}
export default {
 listWebhookLogs,
 getWebhookLog,
 listWorkItemLogs,
 getWorkItemLog,
}
