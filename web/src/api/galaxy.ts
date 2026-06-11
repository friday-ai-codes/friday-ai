import { get } from './client'

// ============================================================================
// Galaxy Node / Edge Types
// ============================================================================

export type GalaxyNodeType
  = | 'chunk_registry'
    | 'symbol'
    | 'endpoint'
    | 'api_wrapper'
    | 'api_call_site'
    | 'repository'

export type GalaxyEdgeType
  = | 'CALL'
    | 'IMPORT'
    | 'SAME_FILE'
    | 'TEST_OF'
    | 'CO_CHANGED'
    | 'SEMANTIC'
    | 'API_CALLS'
    | 'IMPLEMENTS'
    | 'REPO_API_CALL'

export type GitPlatform = 'github' | 'gitlab' | 'gitea' | 'bitbucket'

export interface GalaxyRepoNodeMetadata {
  git_platform: GitPlatform
  space_ids: string[]
  endpoint_count: number
  callsite_count: number
}

export interface GalaxyRepoEdgeMetadata {
  call_count: number
  avg_confidence: number
}

export interface GalaxyNode {
  id: string
  type: GalaxyNodeType
  label: string
  repository_id: string
  file_path: string
  line_start: number
  line_end: number
  metadata: Record<string, unknown>
  degree: number
}

export interface GalaxyEdge {
  id: string
  source: string
  target: string
  edge_type: GalaxyEdgeType
  weight: number
  repository_id: string
  target_repository_id: string | null
  metadata: Record<string, unknown>
}

export interface GalaxyMeta {
  total_nodes: number
  total_edges: number
  sampled: boolean
  per_repo_hint: boolean
  max_nodes: number
  /** 本次响应是否命中后端文件缓存（仅 L1 接口返回） */
  cache_hit?: boolean
}

export interface GalaxyResponse {
  nodes: GalaxyNode[]
  edges: GalaxyEdge[]
  meta: GalaxyMeta
}

export interface GetGalaxyParams {
  repoIds?: string[]
  nodeTypes?: GalaxyNodeType[]
  edgeTypes?: GalaxyEdgeType[]
  maxNodes?: number
}

export interface GalaxySearchResult {
  id: string
  type: GalaxyNodeType
  label: string
  file_path: string
  repository_id: string
  degree: number
  score?: number
}

/** 1-hop 邻居条目（与后端 GalaxyNeighbor TypedDict 对齐） */
export interface GalaxyNeighbor {
  node: GalaxyNode
  edge: GalaxyEdge
  direction: 'outgoing' | 'incoming'
}

/** 节点引用（如调用某 Endpoint 的 ApiCallSite，与后端 GalaxyReference 对齐） */
export interface GalaxyReference {
  type: string
  id: string
  label: string
  repository_id: string
  match_confidence: number
}

export interface GalaxyNodeDetail {
  node: GalaxyNode
  neighbors: GalaxyNeighbor[]
  references: GalaxyReference[]
  called_by: GalaxyReference[]
}

// ============================================================================
// API Functions
// ============================================================================

export async function getGalaxyGraph(params: GetGalaxyParams = {}): Promise<GalaxyResponse> {
  const query: Record<string, string | number | undefined> = {}

  if (params.repoIds && params.repoIds.length > 0)
    query.repo_ids = params.repoIds.join(',')

  if (params.nodeTypes && params.nodeTypes.length > 0)
    query.node_types = params.nodeTypes.join(',')

  if (params.edgeTypes && params.edgeTypes.length > 0)
    query.edge_types = params.edgeTypes.join(',')

  if (params.maxNodes !== undefined)
    query.max_nodes = params.maxNodes

  return get<GalaxyResponse>('/codegraph/galaxy/', query)
}

export async function searchGalaxyNodes(
  q: string,
  maxResults = 20,
): Promise<GalaxySearchResult[]> {
  // 后端参数名为 limit（默认 20，max 100）
  const data = await get<{ results: GalaxySearchResult[] }>('/codegraph/galaxy/search/', {
    q,
    limit: maxResults,
  })
  return data.results
}

export async function getGalaxyNodeDetail(nodeId: string): Promise<GalaxyNodeDetail> {
  const encoded = encodeURIComponent(nodeId)
  return get<GalaxyNodeDetail>(`/codegraph/galaxy/nodes/${encoded}/`)
}

// ============================================================================
// L2: 仓库节点视图（多仓库总览）
// ============================================================================

export interface GalaxyRepoNode extends Omit<GalaxyNode, 'type' | 'metadata'> {
  type: 'repository'
  metadata: GalaxyRepoNodeMetadata
}

export interface GalaxyRepoEdge extends Omit<GalaxyEdge, 'edge_type' | 'metadata'> {
  edge_type: 'REPO_API_CALL'
  metadata: GalaxyRepoEdgeMetadata
}

export interface GalaxyReposResponse {
  nodes: GalaxyRepoNode[]
  edges: GalaxyRepoEdge[]
  meta: GalaxyMeta
}

export interface GetGalaxyReposParams {
  spaceId?: string | null
}

/**
 * L2 仓库节点视图。每个节点 = Repository；每条边 = 同对仓库的 CrossRepoApiCall 聚合。
 * spaceId 可选；不传 = 全部仓库。
 */
export async function getGalaxyRepoGraph(
  params: GetGalaxyReposParams = {},
): Promise<GalaxyReposResponse> {
  const query: Record<string, string | undefined> = {}
  if (params.spaceId)
    query.space_id = params.spaceId
  return get<GalaxyReposResponse>('/codegraph/galaxy/repos/', query)
}
