/**
 * 用户反馈相关类型。
 *
 * 对应后端 server/feedback 的 Feedback / FeedbackReply 模型与序列化器。
 */

export type FeedbackCategory = 'bug' | 'question' | 'feature' | 'other'
export type FeedbackStatus = 'open' | 'in_progress' | 'resolved' | 'closed' | 'wont_fix'

export interface FeedbackAttachment {
  storage_ref: string
  kind: 'image' | 'video'
  name?: string
  size?: number
  mime?: string
  url?: string
}

export interface FeedbackReply {
  id: string
  content: string
  is_admin: boolean
  author_repr: string
  author_name: string
  created_at: string
}

export interface Feedback {
  id: string
  category: FeedbackCategory
  category_label: string
  title: string
  content: string
  attachments: FeedbackAttachment[]
  page_url: string
  conversation_id: string | null
  message_id: string | null
  status: FeedbackStatus
  status_label: string
  created_by_name: string
  replies: FeedbackReply[]
  created_at: string
  updated_at: string
  resolved_at: string | null
}

export interface FeedbackCreatePayload {
  category: FeedbackCategory
  title?: string
  content: string
  attachments?: FeedbackAttachment[]
  page_url?: string
  conversation_id?: string | null
  message_id?: string | null
}

export interface FeedbackListResponse {
  items: Feedback[]
  total: number
  limit: number
  offset: number
}

export interface FeedbackListParams {
  status?: FeedbackStatus
  category?: FeedbackCategory
  search?: string
  limit?: number
  offset?: number
}
