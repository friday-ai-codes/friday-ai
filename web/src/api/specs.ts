/**
 * spec 治理 API（Phase 50 SPECST-03，对齐 50-03 后端契约 + 50-UI-SPEC）。
 *
 * 消费 `/api/specs/` 端点：list（?status / ?repository_id 过滤）/ detail（正文 + 评审历史 +
 * 关联摘要）/ transition（提交评审 / 批准 / 驳回 / 标记已实现 / 归档，经 SddSpecService）。
 * 状态全 read_only：状态仅经 transition action 改（后端 D-50-4）。
 */

import { get, post } from './client'

/** spec 操作态（5 态，对齐后端 SddSpecStatus）。 */
export type SddSpecStatus = 'draft' | 'in_review' | 'approved' | 'implemented' | 'archived'

/** spec 状态流转动作（对齐后端 transition action 集合 + D-50-1）。 */
export type SpecTransitionAction
  = | 'submit_for_review'
    | 'approve'
    | 'reject'
    | 'mark_implemented'
    | 'archive'

/** 单条评审记录（append-only，reviewer 被删→null）。 */
export interface SddSpecReview {
  id: string
  /** 评审人标识（用户被删置空时为 null）。 */
  reviewer: string | null
  decision: 'approve' | 'reject'
  comment: string
  created_at: string
}

/** spec 列表项（轻量，不含正文/评审历史）。 */
export interface SddSpec {
  id: string
  status: SddSpecStatus
  change_kind: string
  repository_id: string
  repository_name: string
  /** 关联需求摘要（无关联时为 null）。 */
  work_item?: { id: string, title: string } | null
  updated_at: string
}

/** 实现 PR 关联项（Phase 52 D-52-4，spec→PR 追溯，对齐后端 implementation_prs 元素）。 */
export interface ImplementationPr {
  pr_url: string
  repository_id: string
  /** 关联时间（ISO8601）。 */
  linked_at: string
}

/** spec 详情（正文 + 评审历史 + 关联摘要 + 实现 PR 追溯）。 */
export interface SddSpecDetail extends SddSpec {
  /** spec 正文 markdown（缺失为 null）。 */
  body: string | null
  /** 评审历史（后端倒序）。 */
  reviews: SddSpecReview[]
  /** 关联摘要（缺失项不返回）。 */
  relations: {
    repository?: { id: string, name: string, methodology?: string | null }
    /** 关联需求摘要；url 取 prd_url（可能为空串）。无 work_item 时该键缺失。 */
    work_item?: { id: string, title: string, url: string }
    plan_version?: { id: string, version: number }
  }
  /** 实现 PR 列表（Phase 52 LINK-01；无回填 → []）。 */
  implementation_prs?: ImplementationPr[]
}

/** list 过滤参数。 */
export interface SpecListParams {
  status?: SddSpecStatus
  repository_id?: string
}

/** transition 请求 body。 */
export interface SpecTransitionBody {
  action: SpecTransitionAction
  comment?: string
}

export const specsApi = {
  /** 列出 spec（可选按状态 / 仓库过滤）。 */
  list: (params?: SpecListParams): Promise<SddSpec[]> =>
    get<SddSpec[]>('/specs/', params as Record<string, string> | undefined),

  /** 取 spec 详情（正文 + 评审历史 + 关联摘要）。 */
  detail: (id: string): Promise<SddSpecDetail> => get<SddSpecDetail>(`/specs/${id}/`),

  /** 发起状态流转，返回更新后的详情。 */
  transition: (id: string, body: SpecTransitionBody): Promise<SddSpecDetail> =>
    post<SddSpecDetail>(`/specs/${id}/transition/`, body),
}
