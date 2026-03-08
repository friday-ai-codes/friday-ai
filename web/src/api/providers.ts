/**
 * Provider API 客户端 — Phase
 *
 * 提供 Provider 列表、模型列表、健康检查 API 调用。
 */
import { get, post } from './client'
import type { ProviderType } from '~/types/provider'
/** 后端返回的 Provider 信息 */
export interface ProviderInfo {
 id: string
 name: string
 icon: string
 credential_type: string
 has_credential: boolean
}
/** 健康检查结果 */
export interface HealthCheckResult {
 provider_type: string
 status: 'available' | 'unavailable'
 latency_ms: number
 error: string | null
}
/** 模型信息 */
export interface ProviderModel {
 id: string
 name: string
 created: number | null
}
/** 获取所有 Provider 列表 */
export async function getProviders: Promise<ProviderInfo> {
 return get<ProviderInfo>('/chat/providers/')
}
/** 获取指定 Provider 的模型列表 */
export async function getProviderModels(providerType: ProviderType): Promise<{ models: ProviderModel }> {
 return get<{ models: ProviderModel }>(`/chat/providers/${providerType}/models/`)
}
/** 执行 Provider 健康检查 */
export async function checkProviderHealth(providerType: ProviderType): Promise<HealthCheckResult> {
 return post<HealthCheckResult>(`/chat/providers/${providerType}/health/`)
}
