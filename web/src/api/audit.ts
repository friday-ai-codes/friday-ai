/**
 * 操作审计查询 / 导出 API 客户端（v0.10.0 AUDITUI-01/02）。
 *
 * 对应后端 server/audit/api/views.py（IsSuperUser，只读）：
 * - GET /api/audit/events/         列表 + 过滤 + offset/limit 分页
 * - GET /api/audit/events/{id}/    详情（before/after 全量）
 * - GET /api/audit/events/export/  CSV/JSON 流式导出（fmt=csv|json，复用过滤）
 *
 * 审计只读：本模块不暴露任何 create/update/delete（呼应 AuditEvent append-only）。
 * 导出走 fetch blob 下载（cookie-JWT 自动携带）。
 */

import { get } from './client'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

/** 审计事件只读形状（与后端 AuditEventSerializer 对齐）。 */
export interface AuditEvent {
  id: string
  actor_id: string | null
  actor_repr: string
  action: string
  target_type: string
  target_id: string
  target_repr: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  source: string
  occurred_at: string
  recorded_at: string
  metadata: Record<string, unknown>
}

/** 列表响应。 */
export interface AuditListResp {
  items: AuditEvent[]
  total: number
  limit: number
  offset: number
}

/** 查询过滤参数（与后端 apply_audit_filters / parse_pagination 对齐）。 */
export interface AuditQuery {
  actor_id?: string
  action?: string
  target_type?: string
  target_id?: string
  source?: string
  occurred_from?: string
  occurred_to?: string
  q?: string
  limit?: number
  offset?: number
}

export type AuditExportFormat = 'csv' | 'json'

/** 把过滤参数序列化为 query string（跳过空值）。 */
function toQueryString(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '')
      sp.append(k, String(v))
  }
  return sp.toString()
}

export const auditApi = {
  /** GET 列表（过滤 + 分页）。 */
  list: async (query: AuditQuery = {}): Promise<AuditListResp> => {
    return get<AuditListResp>(
      '/audit/events/',
      query as Record<string, string | number | undefined>,
    )
  },

  /** GET 详情。 */
  detail: async (id: string): Promise<AuditEvent> => {
    return get<AuditEvent>(`/audit/events/${id}/`)
  },

  /**
   * 导出 CSV / JSON：fetch blob 后触发浏览器下载（cookie-JWT 自动携带）。
   * 复用列表过滤条件（不分页），后端流式返回。
   */
  exportFile: async (
    query: AuditQuery = {},
    fmt: AuditExportFormat = 'csv',
  ): Promise<void> => {
    const { limit: _limit, offset: _offset, ...filters } = query
    const qs = toQueryString({ ...filters, fmt })
    const url = `${API_BASE}/audit/events/export/?${qs}`
    const resp = await fetch(url, { credentials: 'include' })
    if (!resp.ok) {
      let detail = `导出失败 (${resp.status})`
      try {
        const body = await resp.json()
        if (body?.detail)
          detail = body.detail
      }
      catch {
        // 非 JSON 响应，保留默认文案
      }
      throw new Error(detail)
    }
    const blob = await resp.blob()
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = `audit_events.${fmt}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(objectUrl)
  },
}

export default auditApi
