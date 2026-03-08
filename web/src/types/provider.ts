/**
 * Provider 类型系统 — 与后端 ProviderType 枚举保持一致
 *
 * 定义前端所需的 Provider 类型、元数据、分组，以及配置来源层级。
 */
/** Provider 类型，与后端 ProviderType 枚举值完全一致 */
export type ProviderType =
 | 'anthropic'
 | 'openai-responses'
 | 'openai-codex-responses'
 | 'openai-completions'
 | 'google-vertex'
 | 'google-gemini-cli'
 | 'google-antigravity'
/** 配置来源层级 */
export type ConfigSource = 'system' | 'project' | 'conversation' | 'node'
/** Provider 元数据 */
export interface ProviderMeta {
 type: ProviderType
 displayName: string
 icon: string // iconify simple-icons 名称，如 'simple-icons--anthropic'
 group: 'anthropic' | 'openai' | 'google'
 credentialType: 'api_key' | 'service_account_json'
}
/** Provider 分组 */
export interface ProviderGroup {
 label: string
 providers: ProviderMeta
}
export const PROVIDER_REGISTRY: ProviderMeta = [
 { type: 'anthropic', displayName: 'Anthropic Claude', icon: 'simple-icons--anthropic', group: 'anthropic', credentialType: 'api_key' },
 { type: 'openai-responses', displayName: 'OpenAI Responses', icon: 'simple-icons--openai', group: 'openai', credentialType: 'api_key' },
 { type: 'openai-codex-responses', displayName: 'OpenAI Codex', icon: 'simple-icons--openai', group: 'openai', credentialType: 'api_key' },
 { type: 'openai-completions', displayName: 'OpenAI Completions', icon: 'simple-icons--openai', group: 'openai', credentialType: 'api_key' },
 { type: 'google-vertex', displayName: 'Google Vertex AI', icon: 'simple-icons--googlecloud', group: 'google', credentialType: 'service_account_json' },
 { type: 'google-gemini-cli', displayName: 'Google Gemini', icon: 'simple-icons--googlegemini', group: 'google', credentialType: 'api_key' },
 { type: 'google-antigravity', displayName: 'Google Antigravity', icon: 'simple-icons--google', group: 'google', credentialType: 'api_key' },
]
export const PROVIDER_GROUPS: ProviderGroup = [
 { label: 'Anthropic', providers: PROVIDER_REGISTRY.filter(p => p.group === 'anthropic') },
 { label: 'OpenAI', providers: PROVIDER_REGISTRY.filter(p => p.group === 'openai') },
 { label: 'Google', providers: PROVIDER_REGISTRY.filter(p => p.group === 'google') },
]
/** 根据 ProviderType 查找元数据 */
export function getProviderMeta(type: ProviderType): ProviderMeta | undefined {
 return PROVIDER_REGISTRY.find(p => p.type === type)
}
