import type {
 GitCredential,
 Repository,
 RepositoryCreate,
 RepositoryUpdate,
} from '~/types'
import { ApiError, del, get, patch, post, upload } from './client'
// 索引状态枚举
export enum IndexStatus {
 NOT_INDEXED = 'not_indexed',
 INDEXING = 'indexing',
 INDEXED = 'indexed',
 FAILED = 'failed',
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
 //: 统一进度字段
 overall_progress: number
 overall_stage: string
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
 results: SearchResultItem
 total: number
}
// 健康检查响应
export interface HealthCheckResponse {
 status: 'healthy' | 'unhealthy' | 'error' | 'not_configured' | 'warning'
 message?: string
 collections_count?: number
 dimension?: number
 model?: string
}
// Phase: 索引历史记录
export interface IndexHistoryItem {
 id: string
 trigger_type: 'manual' | 'webhook' | 'scheduled'
 status: 'pending' | 'running' | 'completed' | 'failed'
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
 // Phase: 变更文件路径（，Plan 新增）
 changed_files?: {
 added?: string
 modified?: string
 deleted?: string
 }
}
export interface IndexHistoryResponse {
 items: IndexHistoryItem
 total: number
}
// Phase: 索引统计
export interface IndexStatsResponse {
 chunks_total: number
 language_distribution: Record<string, number>
 indexed_files_count: number
 coverage_percent: number
}
// Phase: 集合健康
export interface CollectionHealthResponse {
 status: 'healthy' | 'unhealthy'
 collection_exists: boolean
 points_count: number
 expected_points: number
 points_match: boolean | null
 error?: string
}
// Phase: 索引新鲜度
export interface IndexFreshnessResponse {
 local_sha: string
 remote_sha: string
 is_fresh: boolean | null
 last_indexed_at: string | null
 error: string | null
}
/** Phase: GET branch-indexes 单行，与后端 RepositoryBranchIndex 对齐 */
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
 branches?: string
 recommended_branch?: string | null
}
// Phase: AI 智能描述
export type AISummaryStatus = 'not_started' | 'pending' | 'running' | 'completed' | 'failed'
export interface AISummaryStatusResponse {
 status: AISummaryStatus
 progress: null
 summary: string | null
 generated_at: string | null
 error: string | null
}
export interface GenerateSummaryResponse {
 dispatch_task_id: string
 status: 'pending'
}
// Phase: sync-status 响应（Plan 后端 API）
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
// Phase: refresh-remote-head 响应（Plan 后端 API）
export interface RefreshRemoteHeadResponse {
 remote_head_sha: string
 freshness: 'fresh' | 'stale' | 'unknown'
}
export const repositoriesApi = {
 /**
 * 获取仓库列表
 */
 list: async => {
 return get<Repository>('/repositories/')
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
 * Phase: 分支索引行列表（只读）
 */
 getBranchIndexes: async (id: string): Promise<BranchIndexRow> => {
 return get<BranchIndexRow>(`/repositories/${id}/branch-indexes/`)
 },
 /**
 * 获取索引状态
 */
 getIndexStatus: async (id: string): Promise<IndexStatusResponse> => {
 return get<IndexStatusResponse>(`/repositories/${id}/index/status/`)
 },
 /**
 * 删除索引
 */
 deleteIndex: async (id: string): Promise<void> => {
 await del(`/repositories/${id}/index/delete/`)
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
 checkQdrantHealth: async: Promise<HealthCheckResponse> => {
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
 checkEmbeddingHealth: async: Promise<HealthCheckResponse> => {
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
 * Reranker API 健康检查（使用已保存配置）
 */
 checkRerankerHealth: async: Promise<HealthCheckResponse> => {
 return get<HealthCheckResponse>('/repositories/health/reranker/')
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
 testConnection: async (data: { git_url: string, access_token: string, proxy_url?: string }): Promise<TestConnectionResponse> => {
 return post<TestConnectionResponse>('/repositories/test-connection/', data)
 },
 /**
 * 测试已有仓库的连接
 */
 testRepositoryConnection: async (id: string): Promise<TestConnectionResponse> => {
 return post<TestConnectionResponse>(`/repositories/${id}/test-connection/`)
 },
 // ==================== Phase: 索引可观测性 API ====================
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
 * 获取索引统计
 */
 getIndexStats: async (id: string): Promise<IndexStatsResponse> => {
 return get<IndexStatsResponse>(`/repositories/${id}/index/stats/`)
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
 const err = await response.json.catch( => ({ detail: '下载快照失败' }))
 throw new ApiError(response.status, err.detail || '下载快照失败')
 }
 const blob = await response.blob
 const disposition = response.headers.get('Content-Disposition') || ''
 const filename = disposition.match(/filename="?(.+?)"?$/)?.[1] || `snapshot-${id}.snapshot`
 const a = document.createElement('a')
 a.href = URL.createObjectURL(blob)
 a.download = filename
 a.click
 URL.revokeObjectURL(a.href)
 },
 /**
 * 导入索引快照（恢复上传）
 */
 uploadSnapshot: async (id: string, file: File): Promise<{ message: string, points_count: number }> => {
 const formData = new FormData
 formData.append('snapshot', file)
 return upload<{ message: string, points_count: number }>(`/repositories/${id}/index/snapshot/import/`, formData)
 },
 // ==================== Phase: AI 智能描述 ====================
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
 // ==================== Phase: freshness API ====================
 /**
 * 获取仓库同步状态
 */
 getSyncStatus: async (id: string): Promise<SyncStatusResponse> => {
 return get<SyncStatusResponse>(`/repositories/${id}/sync-status/`)
 },
 /**
 * 触发即时 ls-remote，获取最新远端 HEAD + freshness
 */
 refreshRemoteHead: async (id: string): Promise<RefreshRemoteHeadResponse> => {
 return post<RefreshRemoteHeadResponse>(`/repositories/${id}/refresh-remote-head/`)
 },
}
