/**
 * 项目级关系星图 API（项目作战室 P4）。
 *
 * 消费 `GET /api/projects/{id}/galaxy/`：聚合 项目/feature/工作项/仓库/MR 节点
 * 与关联边，供大盘星图可视化「某 feature 关联了什么」。
 */
import { get } from './client'

export type ProjectGalaxyNodeType
  = 'project' | 'feature' | 'work_item' | 'repository' | 'merge_request'

export interface ProjectGalaxyNode {
  id: string
  type: ProjectGalaxyNodeType
  label: string
  /** 跳转锚点（项目/工作项/仓库/MR 的实体 id；feature 无）。 */
  ref_id?: string
  /** feature 四态。 */
  state?: string
  /** feature 所属模块。 */
  module?: string
  /** MR 状态 / 链接。 */
  status?: string
  url?: string
  [k: string]: unknown
}

export interface ProjectGalaxyEdge {
  source: string
  target: string
  relation: string
}

export interface ProjectGalaxyMeta {
  total_nodes: number
  total_edges: number
  truncated: boolean
}

export interface ProjectGalaxyResponse {
  nodes: ProjectGalaxyNode[]
  edges: ProjectGalaxyEdge[]
  meta: ProjectGalaxyMeta
}

export const projectGalaxyApi = {
  get: (projectId: string): Promise<ProjectGalaxyResponse> =>
    get<ProjectGalaxyResponse>(`/projects/${projectId}/galaxy/`),
}

export default projectGalaxyApi
