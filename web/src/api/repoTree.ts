/**
 * 知识树浏览 API（PageIndex 化）
 *
 * 全局知识金字塔：业务域 → 子域 → 仓库 → 子应用 → 模块 → 能力。
 * 浏览树与 AI 路由同源（ai_summary_tree + repo_index_nodes）。
 */

import { get, post } from './client'

// 仓库卡片（浏览树用轻量字段）
export interface RepoCard {
  repo_id: string
  name: string
  overview: string
  is_monorepo: boolean
  has_tree: boolean
  index_status: string
  facets: Record<string, string>
}

// 业务域/子域节点（递归）
export interface DomainNode {
  id: string
  title: string
  summary: string
  children: DomainNode[]
  repo_ids: string[]
}

export interface KnowledgeTreeResponse {
  view: string
  has_tree: boolean
  tree: DomainNode[]
  repos: Record<string, RepoCard>
  total_repos: number
  snapshot: { version: number, built_by: string, created_at: string } | null
}

export interface FacetGroup {
  value: string
  repo_ids: string[]
}

export interface FacetViewResponse {
  view: string
  dimension: string
  groups: FacetGroup[]
  repos: Record<string, RepoCard>
}

// 树内搜索命中（能力树节点级）
export interface TreeSearchResult {
  repository_id: string
  repo_name: string
  node_id: string
  node_type: string
  title: string
  summary: string
  node_path: string
  sub_project: string
  score: number
}

export interface TreeSearchResponse {
  query: string
  results: TreeSearchResult[]
  total: number
}

// 单仓能力树节点（递归）
export interface CapabilityNode {
  node_id: string
  node_type: 'sub_app' | 'module' | 'capability'
  title: string
  summary: string
  keywords: string[]
  paths: string[]
  children: CapabilityNode[]
}

export interface RepoIndexTreeResponse {
  repository_id: string
  name: string
  is_monorepo: boolean
  tree: CapabilityNode[]
  facets: Record<string, string>
  stale_state: { stale_node_ids?: string[], new_paths?: string[], evaluated_at?: string }
  ai_summary_status: string
  generated_at: string | null
}

/** 全局知识树（业务域视角） */
export function getKnowledgeTree(): Promise<KnowledgeTreeResponse> {
  return get<KnowledgeTreeResponse>('/repositories/knowledge-tree/')
}

/** 分面透视视角 */
export function getFacetView(dimension: string): Promise<FacetViewResponse> {
  return get<FacetViewResponse>('/repositories/knowledge-tree/facet/', { dimension })
}

/** 树内搜索：命中节点 + 完整祖先路径 */
export function searchKnowledgeTree(q: string, topK = 20): Promise<TreeSearchResponse> {
  return get<TreeSearchResponse>('/repositories/knowledge-tree/search/', { q, top_k: topK })
}

/** 单仓完整能力树 */
export function getRepoIndexTree(repositoryId: string): Promise<RepoIndexTreeResponse> {
  return get<RepoIndexTreeResponse>(`/repositories/${repositoryId}/index-tree/`)
}

/** 全量重建业务域树（admin） */
export function rebuildKnowledgeTree(): Promise<{ status: string }> {
  return post<{ status: string }>('/repositories/knowledge-tree/rebuild/')
}

export default {
  getKnowledgeTree,
  getFacetView,
  searchKnowledgeTree,
  getRepoIndexTree,
  rebuildKnowledgeTree,
}
