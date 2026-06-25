/**
 * 项目记忆 + LLM 草稿 API（v0.15.0 Phase 81，对接 Phase 80 后端）。
 *
 * 记忆：自由文本条目（append/edit/supersede，每条带贡献者/时间戳）；
 * 草稿：LLM 从成员会话蒸馏的 pending 提议，人工确认后入库（MEM-04，不自动 active）。
 */

import { del, get, patch, post } from './client'

/** 记忆状态（对齐后端 ProjectMemoryStatus）。 */
export type ProjectMemoryStatus = 'active' | 'superseded'

/** 草稿状态（对齐后端 DraftStatus）。 */
export type DraftStatus = 'pending' | 'confirmed' | 'rejected'

/** 项目记忆条目（响应）。 */
export interface ProjectMemory {
  id: string
  project_id: string
  content: string
  contributor_id: string | null
  status: ProjectMemoryStatus
  created_at: string
  updated_at: string
}

/** 项目记忆草稿（响应，MEM-04）。 */
export interface ProjectMemoryDraft {
  id: string
  project_id: string
  content: string
  status: DraftStatus
  source_conversation_id: string | null
  proposed_by_id: string | null
  confirmed_memory_id: string | null
  created_at: string
  updated_at: string
}

export const projectMemoryApi = {
  /** 记忆列表（active）。 */
  list: (projectId: string): Promise<ProjectMemory[]> =>
    get<ProjectMemory[]>(`/projects/${projectId}/memories/`),

  /** 新增记忆（MEM-01，成员校验 fail-closed）。 */
  create: (projectId: string, content: string): Promise<ProjectMemory> =>
    post<ProjectMemory>(`/projects/${projectId}/memories/`, { content }),

  /** 编辑记忆（MEM-03，保留修订历史）。 */
  edit: (projectId: string, memoryId: string, content: string): Promise<ProjectMemory> =>
    patch<ProjectMemory>(`/projects/${projectId}/memories/${memoryId}/`, { content }),

  /** 废弃记忆（DELETE → supersede）。 */
  supersede: (projectId: string, memoryId: string): Promise<void> =>
    del(`/projects/${projectId}/memories/${memoryId}/`),

  /** 草稿列表（含 pending）。 */
  listDrafts: (projectId: string): Promise<ProjectMemoryDraft[]> =>
    get<ProjectMemoryDraft[]>(`/projects/${projectId}/memory-drafts/`),

  /** 从成员会话蒸馏一条 pending 草稿（MEM-04）。 */
  distill: (projectId: string, conversationId: string): Promise<ProjectMemoryDraft> =>
    post<ProjectMemoryDraft>(`/projects/${projectId}/memory-drafts/`, {
      conversation_id: conversationId,
    }),

  /** 确认草稿入库为 active 记忆（MEM-04）。 */
  confirmDraft: (projectId: string, draftId: string): Promise<ProjectMemory> =>
    post<ProjectMemory>(`/projects/${projectId}/memory-drafts/${draftId}/confirm/`),

  /** 拒绝草稿。 */
  rejectDraft: (projectId: string, draftId: string): Promise<ProjectMemoryDraft> =>
    post<ProjectMemoryDraft>(`/projects/${projectId}/memory-drafts/${draftId}/reject/`),
}

export default projectMemoryApi
