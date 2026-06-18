/**
 * 用户反馈 API 客户端。
 *
 * 对应后端：
 * - 用户端 server/feedback/api/views.py（/api/feedback/...）
 * - 管理端 server/feedback/api/admin_views.py（/api/admin/feedback/...）
 *
 * `client.ts` 自动拼 `/api` 前缀并补末尾 `/`，本模块统一写相对路径。
 */

import type {
  Feedback,
  FeedbackAttachment,
  FeedbackCreatePayload,
  FeedbackListParams,
  FeedbackListResponse,
  FeedbackStatus,
} from '~/types/feedback'
import { get, patch, post, upload } from './client'

export interface FeedbackAttachmentUploadResult extends Required<Omit<FeedbackAttachment, 'name'>> {
  name: string
}

function buildListQuery(params?: FeedbackListParams): Record<string, string | number> {
  const query: Record<string, string | number> = {}
  if (params?.status)
    query.status = params.status
  if (params?.category)
    query.category = params.category
  if (params?.search)
    query.search = params.search
  if (params?.limit != null)
    query.limit = params.limit
  if (params?.offset != null)
    query.offset = params.offset
  return query
}

export const feedbackApi = {
  /** GET /api/feedback/ —— 列出本人反馈。 */
  list: async (params?: FeedbackListParams): Promise<FeedbackListResponse> => {
    return get<FeedbackListResponse>('/feedback/', buildListQuery(params))
  },

  /** POST /api/feedback/ —— 提交反馈。 */
  create: async (payload: FeedbackCreatePayload): Promise<Feedback> => {
    return post<Feedback>('/feedback/', payload)
  },

  /** GET /api/feedback/<id>/ —— 本人反馈详情。 */
  detail: async (id: string): Promise<Feedback> => {
    return get<Feedback>(`/feedback/${id}/`)
  },

  /** POST /api/feedback/attachments/ —— 上传图片/视频附件。 */
  uploadAttachment: async (file: File): Promise<FeedbackAttachmentUploadResult> => {
    const formData = new FormData()
    formData.append('file', file)
    return upload<FeedbackAttachmentUploadResult>('/feedback/attachments/', formData)
  },

  // ==================== 管理端（IsSuperUser） ====================

  /** GET /api/admin/feedback/ —— 全量反馈列表（过滤 + 搜索 + 分页）。 */
  adminList: async (params?: FeedbackListParams): Promise<FeedbackListResponse> => {
    return get<FeedbackListResponse>('/admin/feedback/', buildListQuery(params))
  },

  /** GET /api/admin/feedback/<id>/ —— 反馈详情。 */
  adminDetail: async (id: string): Promise<Feedback> => {
    return get<Feedback>(`/admin/feedback/${id}/`)
  },

  /** POST /api/admin/feedback/<id>/reply/ —— 管理员回复（触发站内信）。 */
  adminReply: async (id: string, content: string): Promise<Feedback> => {
    return post<Feedback>(`/admin/feedback/${id}/reply/`, { content })
  },

  /** PATCH /api/admin/feedback/<id>/ —— 变更状态（可触发站内信）。 */
  adminUpdateStatus: async (
    id: string,
    status: FeedbackStatus,
    notify = true,
  ): Promise<Feedback> => {
    return patch<Feedback>(`/admin/feedback/${id}/`, { status, notify })
  },
}

export default feedbackApi
