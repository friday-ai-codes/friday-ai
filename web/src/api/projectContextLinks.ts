/**
 * 项目上下文关联 API（「生成知识关联」：候选生成 + 审阅 + 人工编辑）。
 *
 * 对应后端 `/api/projects/{id}/context-links/*`（initiatives.ContextLinkService）：
 * - 生成：一键跑 仓库（RepoAssociation）/ 知识实体 / 外部工件 / MR 四类候选；
 * - 审阅：accept / reject；仓库候选走独立 repo-decision（RepoAssociation 状态机）；
 * - 人工编辑：手动添加（external 链接或按 target_id 关联）、删除。
 */

import { del, get, post } from './client'

export type ContextLinkKind = 'knowledge' | 'artifact' | 'merge_request' | 'external'
export type ContextLinkStatus = 'proposed' | 'accepted' | 'rejected'
export type ContextLinkOrigin = 'ai' | 'manual'

export interface ProjectContextLink {
  id: string
  project_id: string
  target_kind: ContextLinkKind
  target_id: string | null
  title: string
  url: string
  score: number
  reason: string
  origin: ContextLinkOrigin
  status: ContextLinkStatus
  created_by_id: string | null
  created_at: string
  updated_at: string
}

/** 仓库候选（来自 RepoAssociation，状态机 proposed→confirmed→verifying→verified|rejected）。 */
export interface ContextLinkRepoCandidate {
  association_id: string
  repository_id: string
  repository_name: string
  git_url: string
  status: string
  score: number
  confidence: string
  reason: string
}

export interface ContextLinksPayload {
  links: ProjectContextLink[]
  repos: ContextLinkRepoCandidate[]
}

export interface ContextLinkGenerateSummary {
  repo_candidates: number
  knowledge_candidates: number
  artifact_candidates: number
  mr_candidates: number
  created: number
  refreshed: number
  skipped: number
}

export interface ContextLinksGenerateResult extends ContextLinksPayload {
  summary: ContextLinkGenerateSummary
}

export interface ContextLinkManualCreate {
  target_kind: ContextLinkKind
  target_id?: string
  title?: string
  url?: string
  reason?: string
}

export const contextLinksApi = {
  list: (projectId: string): Promise<ContextLinksPayload> =>
    get<ContextLinksPayload>(`/projects/${projectId}/context-links/`),

  generate: (projectId: string): Promise<ContextLinksGenerateResult> =>
    post<ContextLinksGenerateResult>(`/projects/${projectId}/context-links/generate/`, {}),

  addManual: (projectId: string, data: ContextLinkManualCreate): Promise<ProjectContextLink> =>
    post<ProjectContextLink>(`/projects/${projectId}/context-links/`, data),

  accept: (projectId: string, linkId: string): Promise<ProjectContextLink> =>
    post<ProjectContextLink>(`/projects/${projectId}/context-links/${linkId}/accept/`, {}),

  reject: (projectId: string, linkId: string): Promise<ProjectContextLink> =>
    post<ProjectContextLink>(`/projects/${projectId}/context-links/${linkId}/reject/`, {}),

  remove: (projectId: string, linkId: string): Promise<void> =>
    del(`/projects/${projectId}/context-links/${linkId}/`),

  repoDecision: (
    projectId: string,
    data: { repository_id: string, action: 'accept' | 'reject' },
  ): Promise<{ applied: boolean, action: string }> =>
    post(`/projects/${projectId}/context-links/repo-decision/`, data),
}

export default contextLinksApi
