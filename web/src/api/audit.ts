/**
 * 审计事件 API 客户端（v0.10 Phase 3）。
 *
 * 对接后端 `/api/audit-events/` 端点（IsSuperUser 守卫）：
 *   - GET  /audit-events/                  分页列表 + 过滤
 *   - GET  /audit-events/export/?format=   CSV/JSON 导出
 *
 * 真正授权在后端 IsSuperUser；前端路由守卫 requiresAdmin 仅 UX 兜底。
 */

import { get } from './client'

/** 审计事件（对齐 AuditEventSerializer）。 */
export interface AuditEvent {
  id: string
  actor: string
  actor_ip: string
  action: string
  target_type: string
  target_id: string
  before_value: unknown | null
  after_value: unknown | null
  source: string
  extra: Record<string, unknown>
  created_at: string
}

/** 审计事件分页列表响应（对齐 DRF PageNumberPagination）。 */
export interface AuditEventListResponse {
  count: number
  next: string | null
  previous: string | null
  results: AuditEvent[]
}

/** 审计事件过滤参数。 */
export interface AuditEventFilters {
  action?: string
  source?: string
  target_type?: string
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}

/**
 * 分页列出审计事件（AUDIT-02）。
 */
export async function listAuditEvents(
  filters?: AuditEventFilters,
): Promise<AuditEventListResponse> {
  const params: Record<string, string | number | boolean | undefined> = {}
  if (filters?.action) params.action = filters.action
  if (filters?.source) params.source = filters.source
  if (filters?.target_type) params.target_type = filters.target_type
  if (filters?.start_date) params.start_date = filters.start_date
  if (filters?.end_date) params.end_date = filters.end_date
  if (filters?.page) params.page = filters.page
  if (filters?.page_size) params.page_size = filters.page_size
  return get<AuditEventListResponse>('/audit-events/', params)
}

/**
 * 构建导出 URL 并触发浏览器下载（不经 fetch wrapper，直接 window.open）。
 */
export function exportAuditEvents(
  format: 'csv' | 'json',
  filters?: Omit<AuditEventFilters, 'page' | 'page_size'>,
): void {
  const API_BASE = import.meta.env.VITE_API_BASE || '/api'
  const params = new URLSearchParams()
  params.set('format', format)
  if (filters?.action) params.set('action', filters.action)
  if (filters?.source) params.set('source', filters.source)
  if (filters?.target_type) params.set('target_type', filters.target_type)
  if (filters?.start_date) params.set('start_date', filters.start_date)
  if (filters?.end_date) params.set('end_date', filters.end_date)
  const url = `${API_BASE}/audit-events/export/?${params.toString()}`
  window.open(url, '_blank')
}

export default {
  listAuditEvents,
  exportAuditEvents,
}
