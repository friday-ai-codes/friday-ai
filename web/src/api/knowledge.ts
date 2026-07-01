import type { ArtifactCarrier } from '~/api/artifacts'
import { get } from './client'

export interface ProvenanceLinks {
  feishu_url?: string | null
  mr_url?: string | null
  session_link?: string | null
}

export interface EntityMetadata {
  entity_id: string
  kind: string
  version: number
  title: string
  valid_at?: string | null
  invalid_at?: string | null
  source_kind: string
  source_id: string
  origin: string
  event_time?: string | null
  project_id?: string | null
  repository_id?: string | null
  provenance: ProvenanceLinks
  superseded_hint?: string | null
}

export interface TimelineNode {
  entity_id: string
  version: number
  kind: string
  title: string
  summary: string
  valid_at?: string | null
  invalid_at?: string | null
  event_time?: string | null
  provenance?: ProvenanceLinks
  code_changes?: EntityMetadata[]
}

export interface RelatedEntity {
  entity_id: string
  kind: string
  relation: string
  depth: number
  metadata?: EntityMetadata
}

/** 命中工件时携带的专有元数据（对齐 96-02 后端序列化输出，仅 origin=artifact 时存在）。 */
export interface KnowledgeSearchArtifactMeta {
  type_key: string
  type_name: string
  carrier: string
  url: string
  artifact_id: string
  project_id: string
  project_name: string
}

export interface KnowledgeSearchResultItem {
  entity_id: string
  kind: string
  title: string
  version: number
  score: number
  provenance: ProvenanceLinks
  llm_grade?: string | null
  llm_reason?: string | null
  origin?: string
  source_kind?: string
  artifact?: KnowledgeSearchArtifactMeta | null
}

/** 交付文档 / 外部依赖聚合（对齐 96-03 后端契约）。 */
export interface ArtifactTypeCount {
  type_key: string
  type_name: string
  carrier: string
  ragable: boolean
  count: number
}

export interface ArtifactOverviewItem {
  artifact_id: string
  title: string
  type_key: string
  type_name: string
  carrier: string
  url: string
  project_id: string
  project_name: string
  updated_at: string | null
}

export interface ArtifactOverview {
  total: number
  types: ArtifactTypeCount[]
  items: ArtifactOverviewItem[]
  truncated: boolean
}

/** 交付文档知识树叶子（对齐 97-01 后端契约）。 */
export interface ArtifactTreeLeaf {
  artifact_id: string
  title: string
  carrier: ArtifactCarrier
  url: string
  updated_at: string | null
}

/** 交付文档知识树类型分组（对齐 97-01 后端契约）。 */
export interface ArtifactTreeTypeGroup {
  type_key: string
  type_name: string
  carrier: string
  ragable: boolean
  count: number
  artifacts: ArtifactTreeLeaf[]
}

/** 交付文档知识树项目节点（对齐 97-01 后端契约）。 */
export interface ArtifactTreeProject {
  project_id: string
  project_name: string
  count: number
  types: ArtifactTreeTypeGroup[]
}

/** 交付文档知识树（项目→类型→工件，对齐 97-01 后端契约，前端零拼装）。 */
export interface ArtifactTree {
  total: number
  projects: ArtifactTreeProject[]
  truncated: boolean
}

function withAsOf(params: Record<string, string | number | boolean | undefined>, asOf?: string | null) {
  if (asOf)
    params.as_of = asOf
  return params
}

export async function getEntity(id: string, options?: { asOf?: string | null }) {
  return get<EntityMetadata>(`/knowledge/entities/${id}/`, withAsOf({}, options?.asOf))
}

export async function getTimeline(
  id: string,
  options?: { asOf?: string | null, includeSuperseded?: boolean },
) {
  return get<TimelineNode[]>(`/knowledge/timeline/${id}/`, {
    ...withAsOf({}, options?.asOf),
    include_superseded: options?.includeSuperseded ? 'true' : undefined,
  })
}

export async function getRelated(
  id: string,
  options?: { asOf?: string | null, direction?: string, maxHops?: number },
) {
  return get<RelatedEntity[]>(`/knowledge/related/${id}/`, {
    ...withAsOf({}, options?.asOf),
    direction: options?.direction ?? 'both',
    max_hops: options?.maxHops ?? 2,
  })
}

export async function searchDeliveryKnowledge(params: {
  q: string
  topK?: number
  projectIds?: string[]
  asOf?: string | null
  includeSuperseded?: boolean
}) {
  return get<KnowledgeSearchResultItem[]>('/knowledge/search/', {
    q: params.q,
    top_k: params.topK ?? 10,
    project_ids: params.projectIds?.join(','),
    ...withAsOf({}, params.asOf),
    include_superseded: params.includeSuperseded ? 'true' : undefined,
  })
}

export async function getArtifactOverview(params?: { typeKey?: string }) {
  return get<ArtifactOverview>('/knowledge/artifacts/overview/', {
    type_key: params?.typeKey,
  })
}

/** 一次加载整棵可见交付文档树（供前端客户端搜索/展开/查看，零拼装）。 */
export async function fetchArtifactTree(): Promise<ArtifactTree> {
  return get<ArtifactTree>('/knowledge/artifacts/tree/')
}

const knowledgeApi = {
  getEntity,
  getTimeline,
  getRelated,
  searchDeliveryKnowledge,
  getArtifactOverview,
  fetchArtifactTree,
}

export default knowledgeApi
