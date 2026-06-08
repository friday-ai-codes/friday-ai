/**
 * Setup API 服务
 * 封装首启向导相关的 API 调用（无需认证，AllowAny）
 */

import { get, post } from './client'

export interface SetupStatus {
  needs_setup: boolean
  is_initialized: boolean
}

export interface SetupInitRequest {
  username: string
  password: string
  display_name?: string
}

/** 首启向导供应商配置入参（Phase 3，POST /api/providers/setup-wizard/）。 */
export interface SetupProviderRequest {
  api_key: string
  base_url: string
  model: string
  name?: string
  context_length?: number | null
  supports_vision?: boolean
}

/** 首启向导供应商配置响应。 */
export interface SetupProviderResponse {
  id: string
  provider_type: string
  name: string
  scope: string
  default_model: string
  is_default: boolean
  claude_code_bound: boolean
  health?: { status: string, latency_ms: number }
}

/**
 * 查询系统初始化状态（AllowAny，无需认证）
 * 路由守卫在 initAuth() 前调用，fail-safe：异常时调用方 catch 按已初始化处理
 */
export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/auth/setup/status/')
}

/**
 * 首启初始化：创建管理员账号
 * Phase 1 最小实现；注意 setup.vue 的 POST 提交保持原始 fetch，
 * initSetup 供外部消费方和测试使用，避免 403 触发全局 auth:forbidden 重定向
 */
export async function initSetup(data: SetupInitRequest): Promise<void> {
  return post<void>('/auth/setup/', data)
}

/**
 * 首启向导供应商一键配置（Phase 3 PROV-01/04/05）。
 *
 * 调用后端编排端点：健康校验（连通/鉴权）→ Fernet 加密落库系统级 anthropic 凭证
 * → 设系统默认 → 绑定 Claude Code。失败时后端返回可操作中文 detail，调用方直接展示。
 */
export async function setupProvider(
  data: SetupProviderRequest,
): Promise<SetupProviderResponse> {
  return post<SetupProviderResponse>('/providers/setup-wizard/', data)
}

export default { getSetupStatus, initSetup, setupProvider }
