/**
 * Provider 类型系统 — 与后端 ProviderType 枚举保持一致
 *
 * 定义前端所需的 Provider 类型、元数据、分组，以及配置来源层级。
 */
/** Provider 类型，与后端 ProviderType 枚举值完全一致 */
export type ProviderType = 'anthropic'
/** 配置来源层级 */
export type ConfigSource = 'system' | 'project' | 'conversation' | 'node'
/** Provider 元数据 */
export interface ProviderMeta {
 type: ProviderType
 displayName: string
 icon: string // iconify simple-icons 名称，如 'simple-icons--anthropic'
 group: 'anthropic'
 credentialType: 'api_key'
}
/** Provider 分组 */
export interface ProviderGroup {
 label: string
 providers: ProviderMeta
}
export const PROVIDER_REGISTRY: ProviderMeta = [
 { type: 'anthropic', displayName: 'Anthropic Claude', icon: 'simple-icons--anthropic', group: 'anthropic', credentialType: 'api_key' },
]
export const PROVIDER_GROUPS: ProviderGroup = [
 { label: 'Anthropic', providers: PROVIDER_REGISTRY },
]
/** 健康检查状态（Phase） */
export interface HealthStatus {
 status: 'unchecked' | 'checking' | 'available' | 'unavailable'
 latencyMs?: number
 error?: string
}
/** 根据 ProviderType 查找元数据 */
export function getProviderMeta(type: ProviderType): ProviderMeta | undefined {
 return PROVIDER_REGISTRY.find(p => p.type === type)
}
