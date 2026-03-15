import type {
 GitCredential,
 Repository,
 RepositoryCreate,
 RepositoryUpdate,
} from '~/types'
import { del, get, patch, post } from './client'
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
// 连接测试响应
export interface TestConnectionResponse {
 success: boolean
 message?: string
 error?: string
 branches?: string
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
 return post<GitCredential>(`/repositories/${id}/credential/access-token`, data)
 },
 /**
 * 删除凭证
 */
 deleteCredential: async (id: string) => {
 await del(`/repositories/${id}/credential/`)
 },
 // ==================== 索引管理 API ====================
 /**
 * 触发仓库索引
 */
 triggerIndex: async (id: string): Promise<IndexTriggerResponse> => {
 return post<IndexTriggerResponse>(`/repositories/${id}/index/`)
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
 const searchParams = new URLSearchParams
 if (params?.limit)
 searchParams.set('limit', String(params.limit))
 if (params?.offset)
 searchParams.set('offset', String(params.offset))
 if (params?.status)
 searchParams.set('status', params.status)
 const qs = searchParams.toString
 return get<IndexHistoryResponse>(`/repositories/${id}/index/history/${qs ? `?${qs}`: ''}`)
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
}
