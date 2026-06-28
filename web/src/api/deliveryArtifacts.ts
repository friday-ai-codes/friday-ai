/**
 * Delivery Artifact 版本轨 / 时间线 API（Chassis v2 · P7，只读）。
 *
 * 对接后端 `delivery/api/artifact_views.py`：列交付物 + 当前版本摘要、单交付物版本时间线、
 * 某版本的下游引用聚合（RepoCodingTask / SddSpec / ArchitectMerge）。
 *
 * 注意：与 `~/api/artifacts`（initiatives 项目工件）是不同领域对象，勿混用。
 */

import { get } from './client'

/** 单个 ArtifactVersion 的时间线条目。 */
export interface ArtifactVersionTimelineEntry {
  id: string
  version_no: number
  created_at: string
  content_hash: string
  /** supersedes 链：被本版本替换的上一版本 id（首版为 null）。 */
  supersedes_id: string | null
  /** 触发产出的 signal/event 引用，回答“为何变成这个版本”。 */
  produced_by_ref: string
  produced_by_session_id: string
  approval_status: string
  /** 是否为交付物当前版本。 */
  is_current: boolean
}

/** Artifact 列表项（含当前版本摘要）。 */
export interface ArtifactSummary {
  id: string
  artifact_type: string
  title: string
  status: string
  work_item_id: string | null
  current_version: ArtifactVersionTimelineEntry | null
  created_at: string
  updated_at: string
}

/** Artifact 时间线详情（列表字段 + 全版本时间线 + 当前版本 markdown 摘要）。 */
export interface ArtifactTimeline extends ArtifactSummary {
  /** 全版本时间线（倒序，最新在前）。 */
  versions: ArtifactVersionTimelineEntry[]
  /** 当前版本经类型渲染器渲染的 markdown 摘要（无渲染器回 null）。 */
  current_version_markdown: string | null
}

/** 引用某版本的编码子任务摘要。 */
export interface CodingTaskRef {
  id: string
  repository_id: string
  status: string
  wave: number
  attempt: number
}

/** 引用某版本的 SDD spec 摘要。 */
export interface SddSpecRef {
  id: string
  repository_id: string
  status: string
  change_kind: string
}

/** 引用某版本的架构师融合摘要。 */
export interface ArchitectMergeRef {
  id: string
  session_id: string
  validation_status: string
  attempt: number
}

/** 某版本的下游引用聚合。 */
export interface ArtifactVersionDownstream {
  artifact_version_id: string
  coding_tasks: CodingTaskRef[]
  sdd_specs: SddSpecRef[]
  architect_merges: ArchitectMergeRef[]
  total: number
}

/** artifact 列表过滤参数（均可选、可组合）。 */
export interface ListArtifactsParams {
  work_item_id?: string
  artifact_type?: string
  space_id?: string
}

/**
 * 列交付物 + 当前版本摘要（按 work_item / artifact_type / space 过滤）。
 */
export async function listArtifacts(
  params: ListArtifactsParams = {},
): Promise<ArtifactSummary[]> {
  const query: Record<string, string> = {}
  if (params.work_item_id)
    query.work_item_id = params.work_item_id
  if (params.artifact_type)
    query.artifact_type = params.artifact_type
  if (params.space_id)
    query.space_id = params.space_id
  return get<ArtifactSummary[]>('/delivery/artifacts/', query)
}

/**
 * 取单个交付物的版本时间线详情。
 */
export async function getArtifactTimeline(artifactId: string): Promise<ArtifactTimeline> {
  return get<ArtifactTimeline>(`/delivery/artifacts/${artifactId}/`)
}

/**
 * 取某 ArtifactVersion 的下游引用聚合。
 */
export async function getArtifactVersionDownstream(
  versionId: string,
): Promise<ArtifactVersionDownstream> {
  return get<ArtifactVersionDownstream>(
    `/delivery/artifact-versions/${versionId}/downstream/`,
  )
}

export default {
  listArtifacts,
  getArtifactTimeline,
  getArtifactVersionDownstream,
}
