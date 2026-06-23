import type { NeighborMetadata } from '~/api/codegraph'
import type {
  GitCredential,
  Repository,
  RepositoryCreate,
  RepositoryUpdate,
} from '~/types'
import { ApiError, del, get, patch, post, put, upload } from './client'

// 索引状态枚举
export enum IndexStatus {
  NOT_INDEXED = 'not_indexed',
  INDEXING = 'indexing',
  INDEXED = 'indexed',
  FAILED = 'failed',
  CANCELLED = 'cancelled',
}

// 索引状态响应
export interface IndexStatusResponse {
  index_status: IndexStatus
  last_indexed_at: string | null
  index_error: string | null
  index_total_chunks: number
  index_processed_chunks: number
  index_write_total: number
  index_write_processed: number
  // INDX-03: 统一进度字段
  overall_progress: number
  overall_stage: string
  // OBS-05: 文件级实时进度
  current_indexing_file: string
  indexed_files_processed: number
  indexed_files_total: number
  // PROG-02: AI 描述生成状态（not_started/pending/running/completed/failed）
  ai_summary_status?: string
  ai_summary_error?: string
}

// 批量建仓响应（BATCH-02）
export interface BatchCreateResponse {
  created: Array<{ id: string, name: string }>
  failed: Array<{ index: number, name: string, error: unknown }>
  created_count: number
  failed_count: number
}

// 超管全部更新索引响应（BATCH-01）
export interface ReindexAllResponse {
  queued: number
  skipped: number
  total: number
}

// OBS-05: 已索引文件清单
export interface IndexedFileItem {
  file_path: string
  file_hash: string
  last_commit_sha: string
  last_commit_authored_at: string | null
  indexed_at: string
}

export interface IndexedFilesResponse {
  items: IndexedFileItem[]
  total: number
  page: number
  page_size: number
}

// 索引触发响应
export interface IndexTriggerResponse {
  message: string
  repository_id: string
  status: IndexStatus
}

// 搜索请求
export interface SearchRequest {
  query: string
  top_k?: number
  filters?: {
    language?: string
    file_pattern?: string
  }
}

// 搜索结果项
export interface SearchResultItem {
  file_path: string
  score: number
  content: string
  language: string
  start_line: number
  end_line: number
  context_header: string
}

// 搜索响应
export interface SearchResponse {
  query: string
  results: SearchResultItem[]
  total: number
}

// 健康检查响应
export interface HealthCheckResponse {
  status: 'healthy' | 'unhealthy' | 'error' | 'not_configured' | 'warning'
  message?: string
  error?: string
  reason?: string
  collections_count?: number
  dimension?: number
  model?: string
}

// : GraphRAG 增量构建状态（与后端 IndexHistorySerializer 对齐）
// 落地后端字段：models.GraphBuildStatus TextChoices 五态。
export type GraphBuildStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

// : 索引历史记录
export interface IndexHistoryItem {
  id: string
  trigger_type: 'manual' | 'webhook' | 'scheduled'
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  from_sha: string | null
  to_sha: string | null
  files_added: number
  files_modified: number
  files_deleted: number
  summary_text: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  // : 变更文件路径（， 新增）
  changed_files?: {
    added?: string[]
    modified?: string[]
    deleted?: string[]
  }
  // : GraphRAG 增量构建可观测字段（ 前端消费）
  // optional 兼容老 IndexHistory 行未回填
  graph_build_status?: GraphBuildStatus
  edge_count?: number
  payload_synced_at?: string | null
  // : 跨仓 API 匹配状态（ migration 0023 后端已落字段）
  cross_repo_match_count?: number
  cross_repo_built_at?: string | null
  // : per-run delta（本次索引新增，区别于累计 edge_count）
  // optional 兼容老 IndexHistory 行未回填 / 旧后端
  symbols_added?: number
  imports_added?: number
  calls_added?: number
  endpoints_added?: number
  chunk_edges_added?: number
  // : 行级 diff（null = 不可计算，前端显示 "—"，区别于真实 0）
  lines_added?: number | null
  lines_deleted?: number | null
}

export interface IndexHistoryResponse {
  items: IndexHistoryItem[]
  total: number
}

// : GraphRAG 真实状态——以 ChunkEdge 表计数为权威事实来源，
// 修复旧前端读 IndexHistory.edge_count 快照（时序边缘场景漏写停在 0）导致的
// "0 语义边"误显示。
export interface GraphRagStatusResponse {
  edge_count: number
  status: GraphBuildStatus
  last_synced_at: string | null
}

// : 索引统计
//
// Qdrant 不可用时后端走降级路径返回 `coverage_percent: null` + 可选 `qdrant_unavailable` / `warning`
// （见 server/repositories/index_views.py RepositoryIndexStatsView.get 降级分支）。前端必须做 null 防御，
// 否则 `.toFixed()` 之类调用会让组件白屏。
export interface IndexStatsResponse {
  chunks_total: number
  language_distribution: Record<string, number>
  indexed_files_count: number
  coverage_percent: number | null
  qdrant_unavailable?: boolean
  warning?: string
}

// : 集合健康
//
// expected_points / points_match 已废弃：曾经用 Repository.index_total_chunks（仅
// 反映"本次 run 的预期 chunks"）与 Qdrant points_count（历史累积）对比，多次
// 重建后必然不匹配 → UI 永远显示"数量不匹配（预期 X）"。新口径只展示绝对值
// + 文件计数（与"已索引文件"面板同源）。
export interface CollectionHealthResponse {
  status: 'healthy' | 'unhealthy'
  collection_exists: boolean
  points_count: number
  indexed_files_count?: number
  error?: string
}

// : 索引新鲜度
export interface IndexFreshnessResponse {
  local_sha: string
  remote_sha: string
  is_fresh: boolean | null
  last_indexed_at: string | null
  error: string | null
}

/** : GET branch-indexes 单行，与后端 RepositoryBranchIndex 对齐 */
export interface BranchIndexRow {
  branch_name: string
  is_base_branch: boolean
  is_stale: boolean
  last_indexed_at: string | null
  last_indexed_commit_sha: string | null
  effective_chunks_count: number
}

// 连接测试响应
export interface TestConnectionResponse {
  success: boolean
  message?: string
  error?: string
  /** 已按 HEAD > main/master > 最近活跃 > 字典序排序 */
  branches?: string[]
  /** 远端 HEAD 所在分支（ls-remote --symref 探测） */
  head_branch?: string | null
  recommended_branch?: string | null
}

// : AI 智能描述
export type AISummaryStatus = 'not_started' | 'pending' | 'running' | 'completed' | 'failed'

/** Claude Code 容器运行日志条目（Runner 实时回传，[task:*] 前缀解析后） */
export interface AISummaryLogEntry {
  /** text=助手文本 / tool_call=工具调用 / result=结果帧 / block / system / message */
  type: string
  content: string
  /** 毫秒时间戳 */
  ts: number
}

export interface AISummaryStatusResponse {
  status: AISummaryStatus
  progress: null
  summary: string | null
  generated_at: string | null
  error: string | null
  /** PageIndex 能力树是否已生成 */
  has_tree: boolean
  is_monorepo: boolean
  /** 能力树节点总数（递归） */
  tree_node_count: number
  /** Claude Code 调用细节（最近 30 条，生成中实时增长） */
  recent_logs?: AISummaryLogEntry[]
}

export interface GenerateSummaryResponse {
  dispatch_task_id: string
  status: 'pending'
}

// : sync-status 响应（ 后端 API）
export interface SyncStatusResponse {
  repository_id: string
  last_synced_sha: string
  last_synced_at: string | null
  last_sync_result: 'success' | 'failed' | 'running' | 'pending' | 'never'
  next_sync_at: string | null
  interval_seconds: number
  recent_history: Array<{
    id: string
    trigger_type: string
    status: string
    from_sha: string
    to_sha: string
    files_added: number
    files_modified: number
    files_deleted: number
    started_at: string | null
    finished_at: string | null
    created_at: string
  }>
}

// : refresh-remote-head 响应（ 后端 API）
export interface RefreshRemoteHeadResponse {
  remote_head_sha: string
  freshness: 'fresh' | 'stale' | 'unknown'
}

export const repositoriesApi = {
  /**
   * 获取仓库列表
   */
  list: async () => {
    return get<Repository[]>('/repositories/')
  },

  /**
   * 获取仓库详情
   */
  get: async (id: string) => {
    return get<Repository>(`/repositories/${id}/`)
  },

  /**
   * 创建仓库（包含 Access Token 凭证）
   */
  create: async (data: RepositoryCreate) => {
    return post<Repository>('/repositories/', data)
  },

  /**
   * 批量建仓（BATCH-02）：接受仓库数组，逐项创建。前端 CSV 导入解析后调用。
   */
  batchCreate: async (repositories: RepositoryCreate[]) => {
    return post<BatchCreateResponse>('/repositories/batch/', { repositories })
  },

  /**
   * 超管「全部更新索引」（BATCH-01）：把全部未删除仓库批量入队，受并发上限排队消费。
   */
  reindexAll: async () => {
    return post<ReindexAllResponse>('/repositories/reindex-all/', {})
  },

  /**
   * 更新仓库
   */
  update: async (id: string, data: RepositoryUpdate) => {
    return patch<Repository>(`/repositories/${id}/`, data)
  },

  /**
   * 删除仓库
   */
  delete: async (id: string) => {
    await del(`/repositories/${id}/`)
  },

  /**
   * 获取凭证信息（不含敏感数据）
   */
  getCredential: async (id: string) => {
    return get<GitCredential>(`/repositories/${id}/credential/`)
  },

  /**
   * 设置/更新 Access Token
   */
  setAccessToken: async (id: string, data: { token: string, git_user_name?: string, git_user_email?: string }) => {
    return post<GitCredential>(`/repositories/${id}/credential/access-token/`, data)
  },

  /**
   * 删除凭证
   */
  deleteCredential: async (id: string) => {
    await del(`/repositories/${id}/credential/`)
  },

  // ==================== 索引管理 API ====================

  /**
   * 触发仓库索引（可选 branch 用于重建指定分支 overlay）
   */
  triggerIndex: async (
    id: string,
    options?: { branch?: string | null },
  ): Promise<IndexTriggerResponse> => {
    if (options?.branch) {
      return post<IndexTriggerResponse>(`/repositories/${id}/index/`, {
        branch: options.branch,
      })
    }
    return post<IndexTriggerResponse>(`/repositories/${id}/index/`)
  },

  /**
   * : 分支索引行列表（只读）
   */
  getBranchIndexes: async (id: string): Promise<BranchIndexRow[]> => {
    return get<BranchIndexRow[]>(`/repositories/${id}/branch-indexes/`)
  },

  /**
   * 获取索引状态
   */
  getIndexStatus: async (id: string): Promise<IndexStatusResponse> => {
    return get<IndexStatusResponse>(`/repositories/${id}/index/status/`)
  },

  /**
   * : 获取 GraphRAG 真实状态（直接 count ChunkEdge 表，不依赖 IndexHistory 快照）
   * : 可选 branch 参数（消费 295 后端 ?branch= 口径，base+overlay 合并）；
   * `branch || undefined` 防 null→"null"，base 态不发 branch query（与现状字节级一致）。
   */
  getGraphRagStatus: async (id: string, branch?: string | null): Promise<GraphRagStatusResponse> => {
    return get<GraphRagStatusResponse>(`/repositories/${id}/index/graphrag-status/`, { branch: branch || undefined })
  },

  /**
   * 删除索引
   */
  deleteIndex: async (id: string): Promise<void> => {
    await del(`/repositories/${id}/index/delete/`)
  },

  /**
   * 停止正在运行的索引任务
   */
  cancelIndex: async (id: string): Promise<IndexTriggerResponse> => {
    return post<IndexTriggerResponse>(`/repositories/${id}/index/cancel/`)
  },

  /**
   * 搜索代码
   */
  searchCode: async (id: string, request: SearchRequest): Promise<SearchResponse> => {
    return post<SearchResponse>(`/repositories/${id}/search/`, request)
  },

  /**
   * Qdrant 健康检查
   */
  checkQdrantHealth: async (): Promise<HealthCheckResponse> => {
    return get<HealthCheckResponse>('/repositories/health/qdrant/')
  },

  /**
   * Qdrant 连接测试（使用提供的配置，保存前测试）
   */
  testQdrantConnection: async (url: string, apiKey?: string): Promise<HealthCheckResponse> => {
    return post<HealthCheckResponse>('/repositories/health/qdrant/', {
      url,
      api_key: apiKey,
    })
  },

  /**
   * Embedding API 健康检查（使用已保存配置）
   */
  checkEmbeddingHealth: async (): Promise<HealthCheckResponse> => {
    return get<HealthCheckResponse>('/repositories/health/embedding/')
  },

  /**
   * Embedding API 健康检查（使用提供的配置，保存前测试）
   */
  testEmbeddingConnection: async (apiUrl: string, model: string, apiKey?: string, dimension?: number): Promise<HealthCheckResponse> => {
    return post<HealthCheckResponse>('/repositories/health/embedding/', {
      api_url: apiUrl,
      model,
      api_key: apiKey,
      dimension,
    })
  },

  /**
   * Reranker API 健康检查（使用提供的配置，保存前测试）
   */
  testRerankerConnection: async (apiUrl: string, model: string, apiKey?: string): Promise<HealthCheckResponse> => {
    return post<HealthCheckResponse>('/repositories/health/reranker/', {
      api_url: apiUrl,
      model,
      api_key: apiKey,
    })
  },

  // ==================== 连接测试 API ====================

  /**
   * 测试仓库连接（新建时使用）
   */
  testConnection: async (data: { git_url: string, access_token?: string, git_instance_credential_id?: string, proxy_url?: string }): Promise<TestConnectionResponse> => {
    return post<TestConnectionResponse>('/repositories/test-connection/', data)
  },

  /**
   * 测试已有仓库的连接
   */
  testRepositoryConnection: async (id: string): Promise<TestConnectionResponse> => {
    return post<TestConnectionResponse>(`/repositories/${id}/test-connection/`)
  },

  // ==================== 关联空间管理 API ====================

  /**
   * 获取仓库关联的空间列表
   */
  getLinkedSpaces: async (id: string): Promise<{ id: string, name: string }[]> => {
    return get<{ id: string, name: string }[]>(`/repositories/${id}/spaces/`)
  },

  /**
   * 全量设置仓库关联空间（至少保留一个）
   */
  setLinkedSpaces: async (id: string, spaceIds: string[]): Promise<{ id: string, name: string }[]> => {
    return put<{ id: string, name: string }[]>(`/repositories/${id}/spaces/`, { space_ids: spaceIds })
  },

  // ==================== : 索引可观测性 API ====================

  /**
   * 生成 Webhook Secret
   */
  generateWebhookSecret: async (id: string): Promise<{ webhook_secret: string }> => {
    return post<{ webhook_secret: string }>(`/repositories/${id}/generate-webhook-secret/`)
  },

  /**
   * 获取索引历史列表（分页 + 状态筛选）
   */
  getIndexHistory: async (id: string, params?: { limit?: number, offset?: number, status?: string }): Promise<IndexHistoryResponse> => {
    return get<IndexHistoryResponse>(`/repositories/${id}/index/history/`, params)
  },

  /**
   * OBS-05: 已索引文件清单查询（支持子串搜索 + 分页）
   */
  getIndexedFiles: async (
    id: string,
    params?: { search?: string, page?: number, page_size?: number },
  ): Promise<IndexedFilesResponse> => {
    return get<IndexedFilesResponse>(`/repositories/${id}/indexed-files/`, params)
  },

  /**
   * 获取索引统计
   * : 可选 branch 参数（edge/图谱维度 branch-aware；chunks_total 仍走 base collection）。
   * `branch || undefined` 防 null→"null"，base 态不发 branch query。
   */
  getIndexStats: async (id: string, branch?: string | null): Promise<IndexStatsResponse> => {
    return get<IndexStatsResponse>(`/repositories/${id}/index/stats/`, { branch: branch || undefined })
  },

  /**
   * 获取集合健康状态
   */
  getCollectionHealth: async (id: string): Promise<CollectionHealthResponse> => {
    return get<CollectionHealthResponse>(`/repositories/${id}/index/health/`)
  },

  /**
   * 获取索引新鲜度
   */
  getIndexFreshness: async (id: string): Promise<IndexFreshnessResponse> => {
    return get<IndexFreshnessResponse>(`/repositories/${id}/index/freshness/`)
  },

  // ==================== 索引快照导入导出 ====================

  /**
   * 导出索引快照（备份下载）
   */
  downloadSnapshot: async (id: string): Promise<void> => {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'

    const response = await fetch(`${baseUrl}/repositories/${id}/index/snapshot/export/`, {
      method: 'POST',
      credentials: 'include',
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '下载快照失败' }))
      throw new ApiError(response.status, err.detail || '下载快照失败')
    }

    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') || ''
    const filename = disposition.match(/filename="?(.+?)"?$/)?.[1] || `snapshot-${id}.snapshot`
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
  },

  /**
   * 导入索引快照（恢复上传）
   */
  uploadSnapshot: async (id: string, file: File): Promise<{ message: string, points_count: number }> => {
    const formData = new FormData()
    formData.append('snapshot', file)
    return upload<{ message: string, points_count: number }>(`/repositories/${id}/index/snapshot/import/`, formData)
  },

  // ==================== : AI 智能描述 ====================

  /**
   * 触发生成 AI 智能描述
   */
  generateSummary: async (id: string): Promise<GenerateSummaryResponse> => {
    return post<GenerateSummaryResponse>(`/repositories/${id}/generate-summary/`)
  },

  /**
   * 获取 AI 描述生成状态
   */
  getSummaryStatus: async (id: string): Promise<AISummaryStatusResponse> => {
    return get<AISummaryStatusResponse>(`/repositories/${id}/summary-status/`)
  },

  // ==================== : freshness API ====================

  /**
   * 获取仓库同步状态（OBS-01 / SYNC-03）
   */
  getSyncStatus: async (id: string): Promise<SyncStatusResponse> => {
    return get<SyncStatusResponse>(`/repositories/${id}/sync-status/`)
  },

  /**
   * 触发即时 ls-remote，获取最新远端 HEAD + freshness（D-13）
   */
  refreshRemoteHead: async (id: string): Promise<RefreshRemoteHeadResponse> => {
    return post<RefreshRemoteHeadResponse>(`/repositories/${id}/refresh-remote-head/`)
  },
}

// ==================== : GSEARCH 仓库级 GraphRAG 关联搜索 ====================

/**
 * L3 命中片段（与 296-02 端点 `results` 序列化对齐）。
 * 作为前端构建扩散图「起点」节点（SourceChunk）的数据源。
 */
export interface GraphSearchResult {
  chunk_id: string
  file_path: string
  line_start: number | null
  line_end: number | null
  content: string
  score: number
  language?: string
}

/**
 * graph-search 端点返回结构（六键，严格对齐 296-02 GraphSearchView）。
 * hop1/hop2 复用 `~/api/codegraph` 的 NeighborMetadata（与后端 `_serialize_neighbor` 同字段集）。
 */
export interface GraphSearchResponse {
  query: string
  results: GraphSearchResult[]
  hop1_neighbors: NeighborMetadata[]
  hop2_neighbors: NeighborMetadata[]
  graph_context: string
  total_tokens: number
}

/**
 * 仓库级 GraphRAG 关联搜索（POST /repositories/{id}/graph-search/）。
 * branch 来自页面 selectedBranch，透传给后端做分支作用域过滤；缺省/空走 base。
 */
export async function graphSearch(
  id: string,
  body: { query: string, branch?: string | null, top_k?: number, max_tokens?: number },
): Promise<GraphSearchResponse> {
  return post<GraphSearchResponse>(`/repositories/${id}/graph-search/`, body)
}
