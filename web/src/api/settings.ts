/**
 * 系统设置 API 服务
 */
import { del, get, post, put } from './client'
// 系统设置键
export enum SettingKey {
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
 // Feishu IM Settings
 FEISHU_APP_ID = 'feishu_app_id',
 FEISHU_APP_SECRET = 'feishu_app_secret',
}
// 设置值读取响应
export interface SettingRead {
 key: string
 value: string | null
 is_encrypted: boolean
 has_value: boolean
 masked_value: string | null
 description: string | null
 updated_at: string | null
}
// Claude 配置读取响应（用于项目）
export interface ClaudeConfigRead {
 has_api_key: boolean
 base_url: string | null
 default_model: string | null
 source: 'project' | 'system' | 'environment'
}
// Claude 配置创建/更新请求
export interface ClaudeConfigCreate {
 api_key?: string
 base_url?: string
 default_model?: string
}
/**
 * 获取单个设置
 */
export async function getSetting(key: SettingKey): Promise<SettingRead> {
 return get<SettingRead>(`/settings/${key}`)
}
/**
 * 获取所有设置
 */
export async function getAllSettings: Promise<SettingRead> {
 return get<SettingRead>('/settings/')
}
/**
 * 更新设置
 */
export async function updateSetting(key: SettingKey, value: string): Promise<SettingRead> {
 return put<SettingRead>(`/settings/${key}`, { value })
}
/**
 * 删除设置
 */
export async function deleteSetting(key: SettingKey): Promise<void> {
 return del(`/settings/${key}`)
}
/**
 * 获取项目的 Claude 配置
 */
export async function getProjectClaudeConfig(projectId: string): Promise<ClaudeConfigRead> {
 return get<ClaudeConfigRead>(`/projects/${projectId}/claude-config/`)
}
/**
 * 更新项目的 Claude 配置
 */
export async function updateProjectClaudeConfig(projectId: string, config: ClaudeConfigCreate): Promise<ClaudeConfigRead> {
 return put<ClaudeConfigRead>(`/projects/${projectId}/claude-config/`, config)
}
/**
 * 删除项目的 Claude 配置
 */
export async function deleteProjectClaudeConfig(projectId: string): Promise<void> {
 return del(`/projects/${projectId}/claude-config/`)
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
 getProjectClaudeConfig,
 updateProjectClaudeConfig,
 deleteProjectClaudeConfig,
}
