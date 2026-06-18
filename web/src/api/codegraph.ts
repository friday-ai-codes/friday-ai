import { del, get, post } from './client'

export interface SymbolRow {
  id: string
  name: string
  symbol_type: 'FUNCTION' | 'CLASS' | 'METHOD' | 'VARIABLE'
  file_path: string
  line_start: number
  line_end: number
  signature: string
  is_async: boolean
}

export interface ImportEdgeRow {
  id: string
  source_file: string
  target_module: string
  imported_names: string[]
  is_relative: boolean
}

export interface EndpointRow {
  id: string
  http_method: string
  url_path: string
  handler_name: string
  view_type: 'FUNCTION_VIEW' | 'CLASS_VIEW' | 'VIEWSET'
  file_path: string
  line_number: number
}

export interface PaginatedResponse<T> {
  count: number
  offset: number
  limit: number
  results: T[]
}

export interface GetSymbolsParams {
  repositoryId: string
  symbolTypes?: string[]
  name?: string
  filePath?: string
  limit?: number
  offset?: number
}

export interface GetImportsParams {
  repositoryId: string
  sourceFile?: string
  limit?: number
  offset?: number
}

export interface GetEndpointsParams {
  repositoryId: string
  limit?: number
  offset?: number
}

export interface DagNode {
  symbol: SymbolRow & { id: string }
  depth: number
  relationship: string
}

export interface DagEdge {
  source: string
  target: string
  call_type: string
}

export interface DagData {
  seed_symbol_id: string
  nodes: DagNode[]
  edges: DagEdge[]
}

export async function getSymbols(params: GetSymbolsParams): Promise<PaginatedResponse<SymbolRow>> {
  const { repositoryId, symbolTypes, name, filePath, limit = 50, offset = 0 } = params
  const query: Record<string, string | number | string[] | undefined> = {
    limit,
    offset,
    name: name || undefined,
    file_path: filePath || undefined,
    symbol_type: symbolTypes && symbolTypes.length > 0 ? symbolTypes : undefined,
  }
  return get<PaginatedResponse<SymbolRow>>(
    `/repositories/${repositoryId}/codegraph/symbols/`,
    query,
  )
}

export async function getCallsForSymbol(
  repositoryId: string,
  symbolId: string,
  hop = 1,
  limit = 50,
): Promise<DagData> {
  return get<DagData>(
    `/repositories/${repositoryId}/codegraph/symbols/${symbolId}/calls/`,
    { max_per_hop: limit, max_total: hop === 2 ? 50 : limit * 2 },
  )
}

// ============================================================================
// 统一邻居查询 + 前端消费
// ============================================================================

export type NeighborNodeType = 'file' | 'component' | 'symbol'
export type NeighborDirection = 'both' | 'up' | 'down'

export interface NeighborNode {
  id: string
  type: NeighborNodeType
  label: string
  file?: string
}

export interface NeighborEdge {
  source: string
  target: string
  kind: string
  count?: number
}

export interface NeighborsData {
  node_type: NeighborNodeType
  direction: NeighborDirection
  nodes: NeighborNode[]
  edges: NeighborEdge[]
}

/**
 * 统一邻居查询（GET /codegraph/graph/neighbors/）。
 * file/component 走查询时聚合，symbol 走符号级 CallEdge（受益 callee_symbol 回填）。
 */
export async function getNeighbors(
  repositoryId: string,
  nodeType: NeighborNodeType,
  id: string,
  direction: NeighborDirection = 'both',
): Promise<NeighborsData> {
  return get<NeighborsData>(
    `/repositories/${repositoryId}/codegraph/graph/neighbors/`,
    { node_type: nodeType, id, direction },
  )
}

export async function getImports(
  repositoryId: string,
  params: Omit<GetImportsParams, 'repositoryId'> = {},
): Promise<PaginatedResponse<ImportEdgeRow>> {
  const { sourceFile, limit = 50, offset = 0 } = params
  return get<PaginatedResponse<ImportEdgeRow>>(
    `/repositories/${repositoryId}/codegraph/imports/`,
    { limit, offset, source_file: sourceFile || undefined },
  )
}

export async function getEndpoints(
  repositoryId: string,
  params: Omit<GetEndpointsParams, 'repositoryId'> = {},
): Promise<PaginatedResponse<EndpointRow>> {
  const { limit = 50, offset = 0 } = params
  return get<PaginatedResponse<EndpointRow>>(
    `/repositories/${repositoryId}/codegraph/endpoints/`,
    { limit, offset },
  )
}

export async function triggerCodegraphIndex(repositoryId: string): Promise<{ message: string }> {
  return post<{ message: string }>(`/repositories/${repositoryId}/codegraph/index/`)
}

// ============================================================================
// Playground Search (TEST-01)
// ============================================================================

export interface PlaygroundSearchParams {
  query: string
  repositoryIds?: string[]
  maxTokens?: number
}

export interface LayerResult {
  layer: string
  status: string
  result_count: number
  items: unknown[]
  error: string | null
  extra: unknown | null
}

export type DiffusionEdgeType
  = | 'CALL'
    | 'IMPORT'
    | 'SAME_FILE'
    | 'TEST_OF'
    | 'CO_CHANGED'
    | 'SEMANTIC'

export interface NeighborMetadata {
  chunk_id: string
  file_path: string
  line_start: number | null
  line_end: number | null
  edge_type: DiffusionEdgeType
  weight: number
  reason: string
  hop: 1 | 2
}

export interface PlaygroundSearchResponse {
  query: string
  repository_ids: string[]
  layers: LayerResult[]
  final_context: string
  total_tokens: number
  hop1_neighbors?: NeighborMetadata[]
  hop2_neighbors?: NeighborMetadata[]
  graph_context?: string
}

export async function playgroundSearch(
  params: PlaygroundSearchParams,
): Promise<PlaygroundSearchResponse> {
  const body: Record<string, unknown> = { query: params.query }
  if (params.repositoryIds && params.repositoryIds.length > 0)
    body.repository_ids = params.repositoryIds
  if (params.maxTokens !== undefined)
    body.max_tokens = params.maxTokens
  return post<PlaygroundSearchResponse>('/codegraph/playground/search/', body)
}

// ============================================================================
// 三件套 + history list + status types
// ============================================================================

/**
 * 图谱构建 5 态（与后端 -01 RepositoryGraphStatus 对齐）
 */
export type GraphBuildStatus
  = | 'idle'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled'

/**
 * 图谱构建触发来源
 */
export type GraphBuildTriggerType
  = | 'manual'
    | 'auto_after_index'
    | 'webhook'

/**
 * 图谱构建历史条目（与后端 RepositoryGraphBuildHistorySerializer 字段对齐）
 */
export interface GraphBuildHistoryItem {
  id: string
  trigger_type: GraphBuildTriggerType
  status: GraphBuildStatus
  files_total: number
  files_processed: number
  files_failed: number
  symbols_count: number
  imports_count: number
  calls_count: number
  endpoints_count: number
  started_at: string | null
  finished_at: string | null
  /** 构建耗时（秒，保留 1 位小数）；仍在构建或缺 started_at 时为 null */
  duration_seconds: number | null
  error_message: string
  created_at: string
}

/**
 * SSE 帧内的 graph payload（与 -02 后端 9 字段精确对齐）
 *
 * 字段命名沿用后端 snake_case，避免在 composable 入口处做 camelCase 转换增加噪音。
 */
export interface GraphPayload {
  status: GraphBuildStatus
  stage: string
  files_processed: number
  files_total: number
  percent: number
  current_file: string
  started_at: string | null
  edge_count_so_far: number
  error_message: string
}

export interface ListGraphHistoryParams {
  limit?: number
  offset?: number
  status?: GraphBuildStatus
}

export interface PaginatedHistoryResponse {
  count: number
  next: string | null
  previous: string | null
  results: GraphBuildHistoryItem[]
}

/**
 * 触发一次图谱重建（POST /codegraph/rebuild/）
 */
export async function rebuildGraph(repositoryId: string): Promise<{ history_id: string }> {
  return post<{ history_id: string }>(`/repositories/${repositoryId}/codegraph/rebuild/`)
}

/**
 * 取消进行中的图谱构建（POST /codegraph/cancel/，204）
 */
export async function cancelGraphBuild(repositoryId: string): Promise<void> {
  await post<void>(`/repositories/${repositoryId}/codegraph/cancel/`)
}

/**
 * 清空图谱数据（DELETE /codegraph/，204）
 */
export async function deleteGraph(repositoryId: string): Promise<void> {
  await del(`/repositories/${repositoryId}/codegraph/`)
}

/**
 * 拉取历史列表（GET /codegraph/history/，DRF 分页）
 */
export async function listGraphHistory(
  repositoryId: string,
  params: ListGraphHistoryParams = {},
): Promise<PaginatedHistoryResponse> {
  const { limit, offset, status } = params
  return get<PaginatedHistoryResponse>(
    `/repositories/${repositoryId}/codegraph/history/`,
    {
      limit,
      offset,
      status,
    },
  )
}
