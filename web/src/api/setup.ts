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

/** 安全密钥校验单条风险（Phase 4 SEC-01）。 */
export interface SecurityRisk {
  code: string
  level: string
}

/** 安全密钥校验结果（GET /api/system/security-check/，只读、非阻塞、不含密钥明文）。 */
export interface SecurityCheck {
  secure: boolean
  secret_key_secure: boolean
  encryption_key_set: boolean
  keys_independent: boolean
  risks: SecurityRisk[]
}

/** 飞书集成配置入参（Phase 4 FEISHU-01/02）。 */
export interface SetupFeishuRequest {
  app_id: string
  app_secret: string
}

/** 向量检索配置入参（Phase 4 RAG-01/02）。 */
export interface SetupRagRequest {
  qdrant_url: string
  qdrant_api_key?: string
  embedding_api_url?: string
  embedding_api_key?: string
  embedding_model?: string
  embedding_dimension?: number | null
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

/**
 * 安全密钥校验（Phase 4 SEC-01）。
 *
 * 只读检测后端 SECRET_KEY / FRIDAY_ENCRYPTION_KEY 是否安全配置，返回布尔判定 + 风险清单。
 * 仅用于向导展示风险提示，绝不阻塞向导完成；响应不含任何密钥明文。
 */
export async function getSecurityCheck(): Promise<SecurityCheck> {
  return get<SecurityCheck>('/system/security-check/')
}

/**
 * 飞书集成可选配置（Phase 4 FEISHU-01/02）。
 *
 * 写入与既有 SystemSetting / bootstrap 路径一致：App ID 明文、App Secret 经 Fernet 加密落库。
 */
export async function setupFeishu(
  data: SetupFeishuRequest,
): Promise<{ feishu_configured: boolean }> {
  return post<{ feishu_configured: boolean }>('/system/setup-feishu/', data)
}

/**
 * 向量检索可选配置（Phase 4 RAG-01/02）。
 *
 * 键名对齐既有 SettingKeys（QDRANT_URL/EMBEDDING_*）；敏感项（API Key）经 Fernet 加密落库。
 */
export async function setupRag(
  data: SetupRagRequest,
): Promise<{ rag_configured: boolean, written_keys: string[] }> {
  return post<{ rag_configured: boolean, written_keys: string[] }>('/system/setup-rag/', data)
}

export default {
  getSetupStatus,
  initSetup,
  setupProvider,
  getSecurityCheck,
  setupFeishu,
  setupRag,
}
