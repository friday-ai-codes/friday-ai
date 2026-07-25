/**
 * OIDC API 服务
 * 封装所有 OIDC 认证相关的 API 调用
 */

import type {
  OIDCAuthorizeResponse,
  OIDCDiscoveryResult,
  OIDCProvider,
  OIDCProviderCreate,
  OIDCProviderPublic,
} from '~/types'
import { del, get, post, put } from './client'

/**
 * 获取所有 OIDC Provider（需认证，管理员用）
 */
export async function getProviders(): Promise<OIDCProvider[]> {
  return get<OIDCProvider[]>('/oidc/providers/')
}

/**
 * 创建 OIDC Provider
 */
export async function createProvider(data: OIDCProviderCreate): Promise<OIDCProvider> {
  return post<OIDCProvider>('/oidc/providers/', data)
}

/**
 * 更新 OIDC Provider
 */
export async function updateProvider(id: string, data: Partial<OIDCProviderCreate>): Promise<OIDCProvider> {
  return put<OIDCProvider>(`/oidc/providers/${id}/`, data)
}

/**
 * 删除 OIDC Provider
 */
export async function deleteProvider(id: string): Promise<void> {
  return del(`/oidc/providers/${id}/`)
}

/**
 * OIDC Discovery — 从 issuer_url 自动填充端点
 */
export async function discoverEndpoints(issuerUrl: string): Promise<OIDCDiscoveryResult> {
  return post<OIDCDiscoveryResult>('/oidc/providers/discovery/', { issuer_url: issuerUrl })
}

/**
 * 获取活跃 OIDC Provider 列表（无需认证，登录页用）
 */
export async function getPublicProviders(): Promise<OIDCProviderPublic[]> {
  return get<OIDCProviderPublic[]>('/oidc/providers/public/')
}

/**
 * 获取 OIDC 授权 URL（无需认证）
 *
 * @param prompt OIDC `prompt` 参数（如 `login` / `consent` / `select_account`）。
 *   主要用于"用户主动退出后下一次登录"传 `login`，强制 IdP 重新认证，
 *   避免 SSO 静默放行导致"点退出无效"的观感。
 */
export async function getAuthorizeUrl(
  providerId: string,
  redirectUri?: string,
  prompt?: 'login' | 'consent' | 'select_account' | 'none',
): Promise<OIDCAuthorizeResponse> {
  const params: Record<string, string> = {}
  if (redirectUri)
    params.redirect_uri = redirectUri
  if (prompt)
    params.prompt = prompt
  return get<OIDCAuthorizeResponse>(
    `/oidc/authorize/${providerId}/`,
    Object.keys(params).length ? params : undefined,
  )
}

export default {
  getProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  discoverEndpoints,
  getPublicProviders,
  getAuthorizeUrl,
}
