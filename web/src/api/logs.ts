/**
 * 日志 API - 触发日志（合并了 Webhook 和工作项日志）
 *
 * 注意：API 路径已从 /api/logs/* 迁移到 /api/feishu/logs/*
 */

import { del, get, post } from './client'

// ============ 常量定义 ============

/**
 * 工作项关键字段常量
 * 用于从飞书工作项中提取关键业务信息
 */
export const KEY_FIELDS = {
  /** 需求文档链接 */
  PRD_URL: 'field_000001',
  /** 需求描述 */
  DESCRIPTION: 'description',
  /** 技术方案文档链接 */
  TECH_DOC_URL: 'field_000009',
} as const

// ============ 类型定义 ============

/**
 * 工作项字段的通用类型
 */
export interface WorkItemField {
  field_key: string
  field_value: unknown
  field_type_key: string
  field_alias: string
  help_description?: string
}

/**
 * 触发日志状态
 */
export type TriggerLogStatus = 'accepted' | 'ignored' | 'error' | 'duplicate'

/**
 * 触发日志（合并了 Webhook 和工作项日志）
 */
export interface TriggerLog {
  id: string
  event_uuid: string | null
  event_type: string
  space_id: string | null
  work_item_id: string | null
  work_item_name: string
  work_item_type: string
  status: TriggerLogStatus
  error_message: string | null
  // 提取的关键字段
  prd_url: string
  description: string
  tech_doc_url: string
  created_at: string
  // 关联执行状态
  execution_status: string | null
  // 首个关联执行 ID（用于交叉导航）
  first_execution_id: string | null
}

/**
 * 关联的工作流执行
 */
export interface LinkedWorkflowExecution {
  id: string
  workflow_id: string
  workflow_name: string
  status: string
  created_at: string
}

/**
 * 触发日志详情（包含原始数据）
 */
export interface TriggerLogDetail extends TriggerLog {
  webhook_raw_request: string
  webhook_raw_request_parsed: Record<string, unknown> | null
  work_item_raw_response: string
  work_item_raw_response_parsed: Record<string, unknown> | null
  workflow_executions: LinkedWorkflowExecution[]
}

/**
 * 日志列表响应
 */
export interface LogListResponse<T> {
  items: T[]
  total: number
}

/**
 * 触发日志查询参数
 */
export interface TriggerLogQuery {
  space_id?: string
  event_type?: string
  status?: TriggerLogStatus
  start_date?: string
  end_date?: string
  limit?: number
  offset?: number
}

// ============ API 方法 ============

/**
 * 获取触发日志列表
 */
export async function listTriggerLogs(
  query: TriggerLogQuery = {},
): Promise<LogListResponse<TriggerLog>> {
  return get<LogListResponse<TriggerLog>>('/feishu/logs/', query as Record<string, string | number | undefined>)
}

/**
 * 获取触发日志详情
 */
export async function getTriggerLog(logId: string): Promise<TriggerLogDetail> {
  return get<TriggerLogDetail>(`/feishu/logs/${logId}/`)
}

/**
 * 删除触发日志
 */
export async function deleteTriggerLog(logId: string): Promise<void> {
  return del(`/feishu/logs/${logId}/delete/`)
}

/**
 * 重试触发日志
 */
export async function retryTriggerLog(logId: string): Promise<{
  status: string
  log_id: string
  result: Record<string, unknown>
}> {
  return post(`/feishu/logs/${logId}/retry/`)
}

export default {
  listTriggerLogs,
  getTriggerLog,
  deleteTriggerLog,
  retryTriggerLog,
}
