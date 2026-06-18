/**
 * 站内信通知 API 客户端。
 *
 * 对应后端 server/notifications/api/views.py（/api/notifications/...）。
 */

import type {
  AppNotification,
  NotificationListParams,
  NotificationListResponse,
} from '~/types/notification'
import { get, post } from './client'

export const notificationsApi = {
  /** GET /api/notifications/ —— 通知列表（分页 + 未读过滤）。 */
  list: async (params?: NotificationListParams): Promise<NotificationListResponse> => {
    const query: Record<string, string | number> = {}
    if (params?.unread)
      query.unread = 'true'
    if (params?.limit != null)
      query.limit = params.limit
    if (params?.offset != null)
      query.offset = params.offset
    return get<NotificationListResponse>('/notifications/', query)
  },

  /** GET /api/notifications/unread-count/ —— 未读数。 */
  unreadCount: async (): Promise<number> => {
    const resp = await get<{ unread: number }>('/notifications/unread-count/')
    return resp.unread
  },

  /** POST /api/notifications/<id>/read/ —— 标记单条已读。 */
  markRead: async (id: string): Promise<AppNotification> => {
    return post<AppNotification>(`/notifications/${id}/read/`, {})
  },

  /** POST /api/notifications/read-all/ —— 全部标记已读。 */
  markAllRead: async (): Promise<{ updated: number }> => {
    return post<{ updated: number }>('/notifications/read-all/', {})
  },
}

export default notificationsApi
