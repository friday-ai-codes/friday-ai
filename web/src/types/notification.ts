/**
 * 站内信通知相关类型。
 *
 * 对应后端 server/notifications 的 Notification 模型与序列化器。
 */

export type NotificationType = 'feedback_reply' | 'feedback_status' | 'system'

export interface AppNotification {
  id: string
  type: NotificationType | string
  title: string
  body: string
  link: string
  metadata: Record<string, unknown>
  read_at: string | null
  is_read: boolean
  created_at: string
}

export interface NotificationListResponse {
  items: AppNotification[]
  total: number
  unread: number
  limit: number
  offset: number
}

export interface NotificationListParams {
  unread?: boolean
  limit?: number
  offset?: number
}
