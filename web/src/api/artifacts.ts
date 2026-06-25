/**
 * 项目工件实例 API（v0.15.0 Phase 81，对接 Phase 79 后端）。
 *
 * 工件挂到项目，记类型/载体/链接/标题/版本/贡献者；支持在线查看
 * （飞书 doc/表格渲染、外链跳转、md/内部内容）。
 */

import { del, get, patch, post } from './client'

/** 工件载体（对齐后端 ArtifactCarrier）。 */
export type ArtifactCarrier =
  | 'feishu_doc'
  | 'feishu_bitable'
  | 'external_link'
  | 'markdown'
  | 'repo_file'

/** 工件实例（响应）。 */
export interface Artifact {
  id: string
  project_id: string
  type_id: string
  type_key: string
  type_name: string
  ragable: boolean
  carrier: ArtifactCarrier
  title: string
  url: string
  content_ref: string
  version: number
  contributor_id: string | null
  created_at: string
  updated_at: string
}

/** 新建工件请求。 */
export interface ArtifactCreate {
  type_id: string
  title: string
  carrier?: ArtifactCarrier | ''
  url?: string
  content_ref?: string
}

/** 工件在线查看数据（ARTIFACT-03）。 */
export interface ArtifactView {
  artifact_id: string
  carrier: ArtifactCarrier
  title: string
  url: string
  version: number
  render_type: 'markdown' | 'text' | 'link' | 'records' | 'unknown'
  content?: string
  records?: Record<string, unknown>[]
  has_more?: boolean
  error?: string
}

export const artifactsApi = {
  /** 工件列表。 */
  list: (projectId: string): Promise<Artifact[]> =>
    get<Artifact[]>(`/projects/${projectId}/artifacts/`),

  /** 新建工件。 */
  create: (projectId: string, data: ArtifactCreate): Promise<Artifact> =>
    post<Artifact>(`/projects/${projectId}/artifacts/`, data),

  /** 工件详情。 */
  get: (projectId: string, artifactId: string): Promise<Artifact> =>
    get<Artifact>(`/projects/${projectId}/artifacts/${artifactId}/`),

  /** 更新工件（md/内部可编辑）。 */
  update: (
    projectId: string,
    artifactId: string,
    data: Partial<Pick<ArtifactCreate, 'title' | 'carrier' | 'url' | 'content_ref'>>,
  ): Promise<Artifact> =>
    patch<Artifact>(`/projects/${projectId}/artifacts/${artifactId}/`, data),

  /** 删除工件。 */
  remove: (projectId: string, artifactId: string): Promise<void> =>
    del(`/projects/${projectId}/artifacts/${artifactId}/`),

  /** 在线查看（飞书 doc/表格渲染、外链元数据、md/内部内容）。 */
  view: (projectId: string, artifactId: string): Promise<ArtifactView> =>
    get<ArtifactView>(`/projects/${projectId}/artifacts/${artifactId}/view/`),
}

export default artifactsApi
