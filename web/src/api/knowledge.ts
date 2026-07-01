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

const knowledgeApi = {
  getEntity,
  getTimeline,
  getRelated,
  searchDeliveryKnowledge,
}

export default knowledgeApi
