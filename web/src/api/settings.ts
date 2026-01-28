/**
 * 系统设置 API 服务
 */
import { del, get, put } from './client'
// 系统设置键
export enum SettingKey {
 ANTHROPIC_API_KEY = 'anthropic_api_key',
 ANTHROPIC_BASE_URL = 'anthropic_base_url',
 GIT_HTTP_PROXY = 'git_http_proxy',
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
 source: 'project' | 'system' | 'environment'
}
// Claude 配置创建/更新请求
export interface ClaudeConfigCreate {
 api_key?: string
 base_url?: string
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
