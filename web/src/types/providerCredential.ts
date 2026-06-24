/**
 * Provider 凭证管理 DTO
 *
 * 与后端 server/system/serializers.py 中的 ProviderCredentialSerializer /
 * ProviderCredentialCreateSerializer / ProviderCredentialUpdateSerializer /
 * ProviderTypeMetaSerializer 字段一一对应。
 */

/** 5 种 Provider 类型（与后端 PROVIDER_REGISTRY 键严格对齐）。 */
export type ProviderType = 'anthropic' | 'openai_responses' | 'openai_chat' | 'gemini' | 'ollama'

/** 凭证作用域。 */
export type ProviderScope = 'system' | 'project'

/**
 * 凭证列表查询入参 scope 类型（仅 query 用，不映射到 DTO.scope）。
 *
 * 'system' / 'project' 与 DB 行 scope 一一对应；'any' 为前端聚合需求
 * （chat 路径 model-selector 需要 system + 当前空间两 scope 全集）。
 *
 * 。
 */
export type ProviderScopeFilter = ProviderScope | 'any'

/**
 * 健康状态。
 *
 * 后端 Serializer 仅返回 `''` / `'ok'` / `'error'` 三态；`'testing'` 为前端乐观 UI 态，
 * 用于「立即测试」按钮点击后到后端响应前的中间态展示。
 */
export type ProviderHealthStatus = '' | 'ok' | 'error' | 'testing'

export type InputModality = 'text' | 'image' | 'audio' | 'video' | 'pdf'

/** 可用模型项（refresh-models 后写入的 available_models 元素）。 */
export interface AvailableModel {
  id: string
  display_name: string
  context_length?: number
  supports_tools?: boolean
  supports_vision?: boolean
  input_modalities?: InputModality[]
  output_modalities?: InputModality[]
  capability_source?: 'known_rules' | 'manual_default' | 'manual' | 'legacy_supports_vision' | string
}

/** Read Serializer 对应的 DTO（与后端 ProviderCredentialSerializer 15 字段对齐）。 */
export interface ProviderCredentialDto {
  id: string
  provider_type: ProviderType
  name: string
  scope: ProviderScope
  scope_id: string | null
  is_active: boolean
  /** 该 (scope, scope_id, provider_type) 维度的默认凭证（替代 name='default' 魔法约定）。 */
  is_default: boolean
  last_health_check_at: string | null
  last_health_check_status: Exclude<ProviderHealthStatus, 'testing'>
  last_health_check_error: string
  available_models: AvailableModel[]
  api_key_last4: string
  has_api_key: boolean
  /**
   * 已解密的 config（按写权限分级回显）。
   *
   * - 非密字段（base_url / organization_id）：所有可读用户均能拿到。
   * - 密字段（api_key / bearer_token）：仅对该凭证有写权限的用户可拿到明文，
   *   否则不出现该 key（前端编辑表单据此判断是否回显 password 输入框初始值）。
   *
   * 后端契约见 server/system/serializers.py::ProviderCredentialSerializer.get_config。
   */
  config: Record<string, unknown>
  /** 默认模型（每个 Provider 必须至少有一个模型）。 */
  default_model: string
  /** 该凭证的 LLM 并发上限（0=不限，默认 50）。由 acquire_llm_slot 限流。 */
  max_concurrency: number
  created_at: string
  updated_at: string
}

/** Pydantic `model_json_schema()` 输出子集（动态表单渲染最小依赖）。 */
export interface JsonSchema {
  type?: string
  title?: string
  properties?: Record<string, JsonSchemaProperty>
  required?: string[]
  [key: string]: unknown
}

export interface JsonSchemaProperty {
  type?: string
  format?: 'password' | 'uri' | string
  title?: string
  description?: string
  default?: unknown
  pattern?: string
  writeOnly?: boolean
  anyOf?: JsonSchemaProperty[]
  [key: string]: unknown
}

/** ProviderTypeMetaSerializer 对应 DTO（GET /api/providers/types/ 单项）。 */
export interface ProviderTypeMetaDto {
  provider_type: ProviderType
  langchain_prefix: string
  supports_thinking: boolean
  supports_reasoning: boolean
  supports_vision: boolean
  credential_schema_json_schema: JsonSchema
  default_model: string | null
}

/** POST /api/providers/credentials/ body。 */
export interface ProviderCredentialCreatePayload {
  provider_type: ProviderType
  name: string
  scope: ProviderScope
  scope_id?: string | null
  /** 按 provider_type 具体字段（api_key / base_url / organization_id / bearer_token 等）。 */
  config: Record<string, unknown>
  is_active?: boolean
  /** 是否设为该维度默认凭证。 */
  is_default?: boolean
  /** 默认模型（每个 Provider 必须至少配置一个模型）。 */
  default_model: string
  /** 绑定到该 Provider 的模型列表（来自接口拉取或手动添加）。 */
  available_models: AvailableModel[]
  /** 该凭证的 LLM 并发上限（0=不限，默认 50）。 */
  max_concurrency?: number
}

/**
 * PATCH /api/providers/credentials/<id>/ body。
 *
 * Pitfall 3 防御：`config` 留 undefined 或 null 表示保留原 config；
 * 传对象时后端会整体重加密覆盖。
 */
export interface ProviderCredentialUpdatePayload {
  name?: string
  scope?: ProviderScope
  scope_id?: string | null
  config?: Record<string, unknown> | null
  is_active?: boolean
  /** 是否设为该维度默认凭证。 */
  is_default?: boolean
  /** 手动设置或刷新后选择的默认模型 */
  default_model?: string
  /** 绑定到该 Provider 的模型列表（来自接口拉取或手动添加）。 */
  available_models?: AvailableModel[]
  /** 该凭证的 LLM 并发上限（0=不限）。 */
  max_concurrency?: number
}

/** POST /test-connection/ 响应（ 既有端点）。 */
export interface TestConnectionResponse {
  status: 'ok' | 'error'
  latency_ms?: number
  error?: string
  last_health_check_at: string
}

/** POST /refresh-models/ 响应。 */
export interface RefreshModelsResponse {
  available_models: AvailableModel[]
  default_model?: string
}

/** POST /api/providers/fetch-models/ body（无状态拉模型，config 不落库）。 */
export interface FetchModelsStatelessPayload {
  provider_type: ProviderType
  config: Record<string, unknown>
}

/** POST /api/providers/fetch-models/ 响应。 */
export interface FetchModelsStatelessResponse {
  available_models: AvailableModel[]
  error?: string
}

// ============================================================================
// Claude Code 编码配置：Claude Code 编码配置
// ============================================================================

/** opus/sonnet/haiku 三档模型映射（值为模型 id，可空）。 */
export interface ClaudeCodeModelMapping {
  opus: string
  sonnet: string
  haiku: string
}

/** GET/PUT /api/providers/claude-code-config/ 读写体。 */
export interface ClaudeCodeConfigPayload {
  credential_id: string
  model_mapping: ClaudeCodeModelMapping
}

/** GET /api/providers/claude-code-config/ 响应（附 credential 展示信息）。 */
export interface ClaudeCodeConfigDto extends ClaudeCodeConfigPayload {
  credential: {
    id: string
    provider_type: ProviderType
    name: string
    scope: ProviderScope
    is_active: boolean
    available_models: AvailableModel[]
  } | null
}

// ============================================================================
// ：四层 Provider 解析 Inspector
// ============================================================================

/** 四层解析链中的单层 layer 标识。 */
export type SourceLayer = 'node' | 'conversation' | 'project' | 'system'

/** 四层解析链条目 — 对应后端 ResolutionChainEntry dataclass。 */
export interface ChainEntry {
  layer: SourceLayer
  provider_type: string | null
  model: string | null
  credential_id: string | null
  active: boolean
}

/** ResolvedProvider 响应对象 — 后端 ProviderConfigService.aresolve_with_chain 平铺结构。 */
export interface ResolvedProvider {
  provider_type: string
  model: string
  /** winning source layer */
  source: SourceLayer
  /** 固定 4 层（顺序：node → conversation → project → system） */
  chain: ChainEntry[]
}
