/**
 * 项目聚合根 API（v0.15.0 Phase 77）。
 *
 * 消费 `/api/projects/` 端点：list / detail / create（PROJ-05，(space, feishu_project_key) 幂等）/
 * update / transition（状态机）/ 成员管理 / 主R 转移。本期前端仅落"创建项目"最小闭环，
 * 完整工作台留 Phase 81。
 */

import { del, get, patch, post } from './client'

/** 项目状态（对齐后端 ProjectStatus）。 */
export type ProjectStatus = 'developing' | 'archived' | 'terminated'

/** 成员身份角色（对齐后端 ProjectRole）。 */
export type ProjectRole = 'owner' | 'pm' | 'frontend' | 'backend' | 'qa'

/** 项目详情（响应）。 */
export interface Project {
  id: string
  space_id: string
  space_name: string
  name: string
  description: string
  status: ProjectStatus
  feishu_project_key: string
  feishu_board_url: string
  feishu_board_id: string
  created_by_id: string | null
  member_count: number
  created_at: string
  updated_at: string
}

/** 创建项目请求（PROJ-05）。 */
export interface ProjectCreate {
  space_id: string
  name: string
  description?: string
  feishu_project_key?: string
  feishu_board_url?: string
  feishu_board_id?: string
}

/** 项目成员（响应）。 */
export interface ProjectMember {
  id: string
  user: { id: string, username: string, display_name: string }
  role: ProjectRole
  created_at: string
}

export const projectsApi = {
  /** 列出对当前用户可见的项目。 */
  list: (): Promise<Project[]> => get<Project[]>('/projects/'),

  /** 项目详情。 */
  get: (id: string): Promise<Project> => get<Project>(`/projects/${id}/`),

  /** 创建项目（幂等：同 (space, feishu_project_key) 返回既有）。 */
  create: (data: ProjectCreate): Promise<Project> => post<Project>('/projects/', data),

  /** 更新项目可变字段。 */
  update: (id: string, data: Partial<ProjectCreate>): Promise<Project> =>
    patch<Project>(`/projects/${id}/`, data),

  /** 状态流转。 */
  transition: (id: string, toStatus: ProjectStatus): Promise<Project> =>
    post<Project>(`/projects/${id}/transition/`, { to_status: toStatus }),

  /** 成员列表。 */
  listMembers: (id: string): Promise<ProjectMember[]> =>
    get<ProjectMember[]>(`/projects/${id}/members/`),

  /** 添加成员。 */
  addMember: (id: string, userId: string, role: ProjectRole): Promise<ProjectMember> =>
    post<ProjectMember>(`/projects/${id}/members/`, { user_id: userId, role }),

  /** 变更成员角色。 */
  updateMemberRole: (id: string, userId: string, role: ProjectRole): Promise<ProjectMember> =>
    patch<ProjectMember>(`/projects/${id}/members/${userId}/`, { role }),

  /** 移除成员。 */
  removeMember: (id: string, userId: string): Promise<void> =>
    del(`/projects/${id}/members/${userId}/`),

  /** 转移主R。 */
  transferOwner: (id: string, newOwnerUserId: string): Promise<ProjectMember[]> =>
    post<ProjectMember[]>(`/projects/${id}/transfer-owner/`, { new_owner_user_id: newOwnerUserId }),
}

export default projectsApi
