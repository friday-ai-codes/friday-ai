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

/** 项目列表筛选参数（UI-01）。 */
export interface ProjectListFilters {
  space_id?: string
  status?: ProjectStatus
  member?: string
  q?: string
}

/** 分页响应包（请求带 limit 时后端返回；供无限滚动按需加载）。 */
export interface ProjectPage {
  results: Project[]
  total: number
  limit: number
  offset: number
}

function filterParams(filters: ProjectListFilters): Record<string, string> {
  const params: Record<string, string> = {}
  if (filters.space_id)
    params.space_id = filters.space_id
  if (filters.status)
    params.status = filters.status
  if (filters.member)
    params.member = filters.member
  if (filters.q)
    params.q = filters.q
  return params
}

/** 项目关联工作项摘要（COMPOSE-01/02）。 */
export interface ProjectWorkItem {
  id: string
  feishu_work_item_id: number
  work_item_type: string
  title: string
  feishu_project_key: string
  provenance: string
  attached_at: string
}

/** 项目知识图谱节点（KLINK-02）。 */
export interface ProjectGraphNode {
  entity_id?: string
  kind?: string
  title?: string
  name?: string
  relation?: string
  depth?: number
  [k: string]: unknown
}

/** Cursor rules 模板（CURSOR-02）。 */
export interface CursorRules {
  filename: string
  content: string
}

/** 项目分支绑定（BIND-01）。 */
export interface ProjectBranch {
  id: string
  repository_id: string
  repository_name: string
  branch_name: string
  source: string
  feishu_board_id: string
  created_at: string
}

/** 绑定分支请求。 */
export interface ProjectBranchBind {
  repository_id: string
  branch_name: string
  source?: string
  feishu_board_id?: string
}

/** 项目「关联仓库」条目（业务关联 ∪ 分支绑定，#4）。 */
export interface ProjectRepoLink {
  /** 关联行 id（association / branch 行）。 */
  id: string
  repository_id: string
  repository_name: string
  git_url: string
  /** 来源：'association'（业务关联）| 'branch'（分支绑定）。 */
  source: 'association' | 'branch'
  status: string
}

export const projectsApi = {
  /** 列出对当前用户可见的项目（支持 space_id/status/member/q 筛选）。 */
  list: (filters: ProjectListFilters = {}): Promise<Project[]> =>
    get<Project[]>('/projects/', filterParams(filters)),

  /** 分页列出项目（created_at 倒序；供列表页无限滚动按需加载）。 */
  listPaged: (
    filters: ProjectListFilters = {},
    page: { limit: number, offset: number },
  ): Promise<ProjectPage> =>
    get<ProjectPage>('/projects/', {
      ...filterParams(filters),
      limit: String(page.limit),
      offset: String(page.offset),
    }),

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

  /** 改归到其他空间（WS-03）。 */
  rehome: (id: string, newSpaceId: string): Promise<Project> =>
    post<Project>(`/projects/${id}/rehome/`, { new_space_id: newSpaceId }),

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

  /** 工作项列表（COMPOSE-01/02）。 */
  listWorkItems: (id: string): Promise<ProjectWorkItem[]> =>
    get<ProjectWorkItem[]>(`/projects/${id}/work-items/`),

  /** 手动并入工作项（work_item_id 为 delivery WorkItem UUID）。 */
  attachWorkItem: (id: string, workItemId: string): Promise<{ attached: boolean }> =>
    post(`/projects/${id}/work-items/`, { work_item_id: workItemId }),

  /** 移除工作项。 */
  detachWorkItem: (id: string, workItemId: string): Promise<void> =>
    del(`/projects/${id}/work-items/${workItemId}/`),

  /** 查询项目在交付知识图谱中的关联（KLINK-02）。 */
  graph: (
    id: string,
    opts: { direction?: 'both' | 'out' | 'in', maxHops?: number, relations?: string } = {},
  ): Promise<{ project_id: string, nodes: ProjectGraphNode[] }> => {
    const params: Record<string, string> = {}
    if (opts.direction)
      params.direction = opts.direction
    if (opts.maxHops != null)
      params.max_hops = String(opts.maxHops)
    if (opts.relations)
      params.relations = opts.relations
    return get(`/projects/${id}/graph/`, params)
  },

  /** 项目专属 Cursor rules 模板（CURSOR-02）。 */
  cursorRules: (id: string): Promise<CursorRules> =>
    get<CursorRules>(`/projects/${id}/cursor-rules/`),

  /** 按 feature list 用 AI 生成/更新项目描述（#2，手动触发）。 */
  generateDescription: (id: string): Promise<{ description: string }> =>
    post<{ description: string }>(`/projects/${id}/description/generate/`, {}),

  /** 项目「关联仓库」（业务关联 ∪ 分支绑定，#4：按项目而非空间，空项目返回 []）。 */
  repositories: (id: string): Promise<ProjectRepoLink[]> =>
    get<ProjectRepoLink[]>(`/projects/${id}/repositories/`),

  /** 项目分支绑定列表（BIND-01）。 */
  listBranches: (id: string): Promise<ProjectBranch[]> =>
    get<ProjectBranch[]>(`/projects/${id}/branches/`),

  /** 绑定分支（严格按分支名，配合 skills 分支→项目反查；空项目亦可绑定）。 */
  bindBranch: (id: string, data: ProjectBranchBind): Promise<ProjectBranch> =>
    post<ProjectBranch>(`/projects/${id}/branches/`, data),

  /** 解绑分支。 */
  unbindBranch: (id: string, branchId: string): Promise<void> =>
    del(`/projects/${id}/branches/${branchId}/`),
}

export default projectsApi
