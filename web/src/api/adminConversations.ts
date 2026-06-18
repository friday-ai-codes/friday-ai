/**
 * 管理员只读会话后台 API 服务（ADMVW-01/02/03）。
 *
 * 对接 09-02 后端物理分离端点 `/api/admin/conversations/`（IsSuperUser 守卫）：
 *   - GET  /admin/conversations/            跨用户只读列表（含 owner + message_count）
 *   - GET  /admin/conversations/<id>/       只读详情 + 消息（写方法后端自动 405）
 *   - POST /admin/conversations/<id>/fork/  fork-to-own → { conversation_id }
 *
 * 真正授权在后端 IsSuperUser；前端路由守卫 requiresAdmin 仅 UX 兜底。
 */

import type { ConversationMessage } from '~/types/chat'
import { get, post } from './client'

/** 会话 owner 简要信息（admin 列表跨用户展示用，历史/匿名会话可能为 null）。 */
export interface AdminConversationOwner {
  id: string
  username: string
  display_name: string
}

/** 管理员会话列表项（对齐 AdminConversationListSerializer）。 */
export interface AdminConversationListItem {
  id: string
  title: string
  status: string
  message_count: number
  owner: AdminConversationOwner | null
  space_id: string
  model?: string
  /** 列表徽标聚合：是否产出过 SDD spec / 技术方案 / 编码会话。 */
  has_sdd_spec?: boolean
  has_coding_plan?: boolean
  has_coding_session?: boolean
  created_at: string
  updated_at: string
}

/** 管理员会话详情（对齐 ConversationDetailSerializer + messages）。 */
export interface AdminConversationDetail {
  id: string
  space_id: string
  title: string
  status: string
  model?: string
  created_at: string
  updated_at: string
  messages: ConversationMessage[]
}

/** fork-to-own 响应。 */
export interface AdminForkResult {
  conversation_id: string
}

/**
 * 跨用户列出全部会话（ADMVW-01）。
 * @param params 可选 owner_id / q 过滤
 */
export async function listAdminConversations(
  params?: { owner_id?: string, q?: string },
): Promise<AdminConversationListItem[]> {
  const query: Record<string, string> = {}
  if (params?.owner_id)
    query.owner_id = params.owner_id
  if (params?.q)
    query.q = params.q
  const qs = new URLSearchParams(query).toString()
  const suffix = qs ? `?${qs}` : ''
  return get<AdminConversationListItem[]>(`/admin/conversations/${suffix}`)
}

/**
 * 取单个会话详情含消息（只读，ADMVW-01/02）。
 */
export async function getAdminConversation(
  id: string,
): Promise<AdminConversationDetail> {
  return get<AdminConversationDetail>(`/admin/conversations/${id}/`)
}

/**
 * fork 会话到当前管理员名下（ADMVW-03）。
 */
export async function forkAdminConversation(
  id: string,
): Promise<AdminForkResult> {
  return post<AdminForkResult>(`/admin/conversations/${id}/fork/`, {})
}

export default {
  listAdminConversations,
  getAdminConversation,
  forkAdminConversation,
}
