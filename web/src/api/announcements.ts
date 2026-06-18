/**
 * 系统公告 API 客户端。
 *
 * 对应后端：
 * - 用户端 server/notifications/api/announcement_views.py（/api/announcements/...）
 * - 管理端 server/notifications/api/admin_views.py（/api/admin/announcements/...）
 *
 * `client.ts` 自动拼 `/api` 前缀并补末尾 `/`，本模块统一写相对路径。
 */

import type {
  AdminAnnouncement,
  AdminAnnouncementListParams,
  AdminAnnouncementListResponse,
  AnnouncementPayload,
  AnnouncementReadStatusResponse,
  UserAnnouncement,
  UserAnnouncementListResponse,
} from '~/types/announcement'
import { del, get, patch, post, put } from './client'

function buildAdminQuery(params?: AdminAnnouncementListParams): Record<string, string | number> {
  const query: Record<string, string | number> = {}
  if (params?.status)
    query.status = params.status
  if (params?.search)
    query.search = params.search
  if (params?.limit != null)
    query.limit = params.limit
  if (params?.offset != null)
    query.offset = params.offset
  return query
}

export const announcementsApi = {
  // ==================== 用户端 ====================

  /** GET /api/announcements/ —— 当前用户可见的公告列表。 */
  list: async (unreadOnly = false): Promise<UserAnnouncementListResponse> => {
    return get<UserAnnouncementListResponse>(
      '/announcements/',
      unreadOnly ? { unread_only: 'true' } : undefined,
    )
  },

  /** GET /api/announcements/unread-count/ —— 未读公告数。 */
  unreadCount: async (): Promise<number> => {
    const resp = await get<{ unread: number }>('/announcements/unread-count/')
    return resp.unread
  },

  /** GET /api/announcements/popup/ —— 登录后需弹窗的公告（popup 模式 + 未读）。 */
  popup: async (): Promise<UserAnnouncement[]> => {
    const resp = await get<{ items: UserAnnouncement[] }>('/announcements/popup/')
    return resp.items
  },

  /** POST /api/announcements/<id>/read/ —— 标记单条公告已读。 */
  markRead: async (id: string): Promise<void> => {
    await post(`/announcements/${id}/read/`, {})
  },

  // ==================== 管理端（IsSuperUser） ====================

  /** GET /api/admin/announcements/ —— 公告列表（过滤 + 分页）。 */
  adminList: async (params?: AdminAnnouncementListParams): Promise<AdminAnnouncementListResponse> => {
    return get<AdminAnnouncementListResponse>('/admin/announcements/', buildAdminQuery(params))
  },

  /** GET /api/admin/announcements/<id>/ —— 公告详情。 */
  adminDetail: async (id: string): Promise<AdminAnnouncement> => {
    return get<AdminAnnouncement>(`/admin/announcements/${id}/`)
  },

  /** POST /api/admin/announcements/ —— 创建公告。 */
  adminCreate: async (payload: AnnouncementPayload): Promise<AdminAnnouncement> => {
    return post<AdminAnnouncement>('/admin/announcements/', payload)
  },

  /** PUT /api/admin/announcements/<id>/ —— 全量更新公告。 */
  adminUpdate: async (id: string, payload: AnnouncementPayload): Promise<AdminAnnouncement> => {
    return put<AdminAnnouncement>(`/admin/announcements/${id}/`, payload)
  },

  /** PATCH /api/admin/announcements/<id>/ —— 部分更新（如仅改状态）。 */
  adminPatch: async (id: string, payload: Partial<AnnouncementPayload>): Promise<AdminAnnouncement> => {
    return patch<AdminAnnouncement>(`/admin/announcements/${id}/`, payload)
  },

  /** DELETE /api/admin/announcements/<id>/ —— 删除公告。 */
  adminDelete: async (id: string): Promise<void> => {
    await del(`/admin/announcements/${id}/`)
  },

  /** GET /api/admin/announcements/<id>/read-status/ —— 按用户已读状态。 */
  adminReadStatus: async (
    id: string,
    params?: { search?: string, limit?: number, offset?: number },
  ): Promise<AnnouncementReadStatusResponse> => {
    const query: Record<string, string | number> = {}
    if (params?.search)
      query.search = params.search
    if (params?.limit != null)
      query.limit = params.limit
    if (params?.offset != null)
      query.offset = params.offset
    return get<AnnouncementReadStatusResponse>(`/admin/announcements/${id}/read-status/`, query)
  },
}

export default announcementsApi
