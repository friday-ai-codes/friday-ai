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

// 默认导出
export default {
  getSetting,
  getAllSettings,
  updateSetting,
  deleteSetting,
}
