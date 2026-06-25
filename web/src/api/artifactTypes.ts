/**
 * 工件类型注册表 API（v0.15.0 Phase 81，对接 Phase 79 后端，超管 CRUD）。
 *
 * 内置类型 builtin=True 禁删；有实例的类型禁删；禁用即 enabled=False
 * （不可新建实例、既有只读保留）。
 */

import type { ArtifactCarrier } from './artifacts'
import { del, get, patch, post } from './client'

/** 工件类型（响应）。 */
export interface ArtifactType {
  id: string
  key: string
  name: string
  carrier: ArtifactCarrier
  ragable: boolean
  enabled: boolean
  builtin: boolean
  instance_count: number
  created_at: string
  updated_at: string
}

/** 新增自定义工件类型请求。 */
export interface ArtifactTypeCreate {
  key: string
  name: string
  carrier: ArtifactCarrier
  ragable?: boolean
  enabled?: boolean
}

/** 全部可选载体（与后端 ArtifactCarrier 对齐）。 */
export const ARTIFACT_CARRIERS: ArtifactCarrier[] = [
  'feishu_doc',
  'feishu_bitable',
  'external_link',
  'markdown',
  'repo_file',
]

export const artifactTypesApi = {
  /** 工件类型列表（已认证可读）。 */
  list: (): Promise<ArtifactType[]> => get<ArtifactType[]>('/artifact-types/'),

  /** 新增自定义类型（超管）。 */
  create: (data: ArtifactTypeCreate): Promise<ArtifactType> =>
    post<ArtifactType>('/artifact-types/', data),

  /** 更新/启停类型（超管）。 */
  update: (
    typeId: string,
    data: Partial<Pick<ArtifactType, 'name' | 'carrier' | 'ragable' | 'enabled'>>,
  ): Promise<ArtifactType> => patch<ArtifactType>(`/artifact-types/${typeId}/`, data),

  /** 删除类型（超管，builtin/有实例 → 409）。 */
  remove: (typeId: string): Promise<void> => del(`/artifact-types/${typeId}/`),
}

export default artifactTypesApi
