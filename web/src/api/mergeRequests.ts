/**
 * 项目 MR/PR 实体 API（v0.15.0 Phase 81，对接 Phase 80 后端）。
 *
 * MR 关联项目/仓库/分支/工作项，记源·目标分支 + 状态 + review 状态 + 平台，
 * 入站 webhook 同步；项目内可见（只读列表）。
 */

import { get } from './client'

/** MR 平台（对齐后端 MRPlatform）。 */
export type MRPlatform = 'github' | 'gitlab'

/** MR 状态（对齐后端）。 */
export type MRStatus = 'open' | 'merged' | 'closed'

/** MR review 状态。 */
export type MRReviewStatus = string

/** MR 实体（响应）。 */
export interface MergeRequest {
  id: string
  project_id: string | null
  repository_id: string | null
  work_item_id: string | null
  platform: MRPlatform
  external_id: string
  url: string
  title: string
  source_branch: string
  target_branch: string
  status: MRStatus
  review_status: MRReviewStatus
  created_at: string
  updated_at: string
}

export const mergeRequestsApi = {
  /** 项目 MR 列表（项目内可见）。 */
  list: (projectId: string): Promise<MergeRequest[]> =>
    get<MergeRequest[]>(`/projects/${projectId}/merge-requests/`),
}

export default mergeRequestsApi
