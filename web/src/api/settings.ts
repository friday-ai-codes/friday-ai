/**
 * 系统设置 API 服务
 */

import { del, get, post, put } from './client'

// 系统设置键
export enum SettingKey {
  // 站点配置
  SITE_HOST = 'site_host',
  ANTHROPIC_API_KEY = 'anthropic_api_key',
  ANTHROPIC_BASE_URL = 'anthropic_base_url',
  ANTHROPIC_MODEL = 'anthropic_model',
  GIT_HTTP_PROXY = 'git_http_proxy',
  // Vector Index Settings
  QDRANT_URL = 'qdrant_url',
  QDRANT_API_KEY = 'qdrant_api_key',
  EMBEDDING_API_URL = 'embedding_api_url',
  EMBEDDING_API_KEY = 'embedding_api_key',
  EMBEDDING_MODEL = 'embedding_model',
  EMBEDDING_DIMENSION = 'embedding_dimension',
  // RAG Enhancement Settings
  RERANKER_ENABLED = 'reranker_enabled',
  RERANKER_API_URL = 'reranker_api_url',
  RERANKER_API_KEY = 'reranker_api_key',
  RERANKER_MODEL = 'reranker_model',
  RERANKER_TOP_N = 'reranker_top_n',
  RERANKER_PROVIDER = 'reranker_provider',
  RERANK_FETCH_K = 'rerank_fetch_k',
  HEURISTIC_RERANK_ENABLED = 'heuristic_rerank_enabled',
  HYBRID_SEARCH_ENABLED = 'hybrid_search_enabled',
  HYBRID_SEARCH_ALPHA = 'hybrid_search_alpha',
  // Feishu IM Settings
  FEISHU_APP_ID = 'feishu_app_id',
  FEISHU_APP_SECRET = 'feishu_app_secret',
  FEISHU_ENCRYPT_KEY = 'feishu_encrypt_key',
  FEISHU_SIGNATURE_REQUIRED = 'feishu_signature_required',
  // Infrastructure Settings
  REDIS_URL = 'redis_url',
  SUBAGENT_API_URL = 'subagent_api_url',
  FRIDAY_BASE_URL = 'friday_base_url',
  FRIDAY_FRONTEND_URL = 'friday_frontend_url',
  CONTAINER_CALLBACK_TOKEN = 'container_callback_token',
}

// 设置值读取响应
export interface SettingRead {
  key: string
  value: string | null
  is_encrypted: boolean
  has_value: boolean
  description: string | null
  updated_at: string | null
}

/**
 * 获取单个设置
 */
export async function getSetting(key: SettingKey): Promise<SettingRead> {
  return get<SettingRead>(`/settings/${key}/`)
}

/**
 * 获取所有设置
 */
export async function getAllSettings(): Promise<SettingRead[]> {
  return get<SettingRead[]>('/settings/')
}

/**
 * 更新设置
 */
export async function updateSetting(key: SettingKey, value: string): Promise<SettingRead> {
  return put<SettingRead>(`/settings/${key}/`, { value })
}

/**
 * 删除设置
 */
export async function deleteSetting(key: SettingKey): Promise<void> {
  return del(`/settings/${key}/`)
}

/**
 * 测试飞书 IM 配置
 */
export async function testFeishuIM(params: {
  receive_id: string
  receive_id_type?: 'open_id' | 'chat_id' | 'user_id'
  message?: string
  app_id?: string
  app_secret?: string
}): Promise<{ success: boolean, message: string, message_id?: string }> {
  return post('/settings/feishu-im/test/', params)
}

// ============================================================================
// 仓库路由权重配置（Phase 106，ROUTE-06）
//
// 走专用端点（服务端强校验：离散网格 / INV-R2 文本主导 / 常数范围），
// **不新增 SettingKey enum 值、不走通用 per-key updateSetting**——通用 PUT
// 无业务校验，权重配置必须经本端点写入。
// ============================================================================

/** 仓库路由多信号权重配置（与后端 DEFAULT_WEIGHT_CONFIG 形状对齐）。 */
export interface RepoRouterWeightConfig {
  /** 权重集版本号——修改权重时应同步更新；不同版本的路由结果不可比 */
  weight_set_version: string
  /** 五信号加性权重（text/domain/activity/stack/team），取值限离散网格 */
  weights: Record<string, number>
  /** 打分常数（lam/b/n_cap/half_life_days/…）；n_bar 可为 null */
  constants: Record<string, number | null>
  /** 关键程度锚点表（档位 → [0,1] 锚点值） */
  criticality_anchors: Record<string, number>
  /** C_crit 加性方案预留权重位（当前不参与计算） */
  crit_weight_reserved: number
  /** O-2 校准判废弃 T2 通道的 facet 列表 */
  t2_disabled_facets: string[]
  /** 校准所用 embedding 模型 id（换模型必须重校准） */
  embedding_model_id: string | null
  /** 最近一次 O-2 校准时间 */
  calibrated_at: string | null
  /** GET 独有：SystemSetting 行不存在（当前生效为内置默认值）时为 true */
  is_default?: boolean
}

/**
 * 读取当前生效的仓库路由权重配置（含 is_default 默认态标注）
 */
export async function getRepoRouterWeightConfig(): Promise<RepoRouterWeightConfig> {
  return get<RepoRouterWeightConfig>('/settings/repo-router/weight-config/')
}

/**
 * 保存仓库路由权重配置（仅 superuser；400 时 body 为 {detail, errors: string[]}）
 *
 * 注意：payload 不得携带 `is_default`（后端校验拒绝未知顶层键）。
 */
export async function putRepoRouterWeightConfig(
  config: Omit<RepoRouterWeightConfig, 'is_default'>,
): Promise<RepoRouterWeightConfig> {
  return put<RepoRouterWeightConfig>('/settings/repo-router/weight-config/', config)
}

// 默认导出
export default {
  getSetting,
  getAllSettings,
  updateSetting,
  deleteSetting,
  getRepoRouterWeightConfig,
  putRepoRouterWeightConfig,
}
