/**
 * 系统公告相关类型。
 *
 * 对应后端 server/notifications 的 Announcement / AnnouncementRead 模型与序列化器。
 */

export type AnnouncementStatus = 'draft' | 'active' | 'archived'
export type AnnouncementNotifyMode = 'silent' | 'popup'
export type AnnouncementAudience = 'all' | 'specific'

/** 面向用户的公告（含已读态），与站内信 AppNotification 形态对齐便于在消息中心合并展示。 */
export interface UserAnnouncement {
  id: string
  /** 区分项类型：固定为 'announcement'，用于合并展示时与站内信区分。 */
  kind: 'announcement'
  type: 'system' | string
  title: string
  body: string
  link: string
  notify_mode: AnnouncementNotifyMode
  read_at: string | null
  is_read: boolean
  created_at: string
}

export interface UserAnnouncementListResponse {
  items: UserAnnouncement[]
  total: number
  unread: number
}

/** 管理端公告完整形态。 */
export interface AdminAnnouncement {
  id: string
  title: string
  body: string
  link: string
  status: AnnouncementStatus
  notify_mode: AnnouncementNotifyMode
  audience: AnnouncementAudience
  target_user_ids: string[]
  starts_at: string | null
  ends_at: string | null
  created_by: string | null
  created_by_name: string
  created_at: string
  updated_at: string
}

export interface AdminAnnouncementListResponse {
  items: AdminAnnouncement[]
  total: number
  limit: number
  offset: number
}

export interface AdminAnnouncementListParams {
  status?: AnnouncementStatus
  search?: string
  limit?: number
  offset?: number
}

export interface AnnouncementPayload {
  title: string
  body: string
  link?: string
  status?: AnnouncementStatus
  notify_mode?: AnnouncementNotifyMode
  audience?: AnnouncementAudience
  target_user_ids?: string[]
  starts_at?: string | null
  ends_at?: string | null
}

/** 某公告的按用户已读状态行。 */
export interface AnnouncementReadStatusRow {
  user_id: string
  username: string
  email: string
  eligible: boolean
  read_at: string | null
}

export interface AnnouncementReadStatusResponse {
  items: AnnouncementReadStatusRow[]
  total: number
  limit: number
  offset: number
}
