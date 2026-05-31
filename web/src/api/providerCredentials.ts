/**
 * Provider 凭证管理 API 客户端（Phase）
 *
 * 对应后端 server/system/views.py:ProviderCredentialViewSet（CRUD 5 端点 + 2 @action）、
 * ProviderTypesView（GET /api/providers/types/）、
 * ProviderCredentialTestConnectionView（Phase 既有 test-connection 端点）。
 *
 * `client.ts` 自动拼 `/api` 前缀且在末尾补 `/`（Django 301 规避），
 * 本模块统一写相对路径 `/providers/credentials/...`。
 */
import type {
 ClaudeCodeConfigDto,
 ClaudeCodeConfigPayload,
 FetchModelsStatelessPayload,
 FetchModelsStatelessResponse,
 ProviderCredentialCreatePayload,
 ProviderCredentialDto,
 ProviderCredentialUpdatePayload,
 ProviderScopeFilter,
 ProviderTypeMetaDto,
 RefreshModelsResponse,
 TestConnectionResponse,
} from '~/types/providerCredential'
import { del, get, patch, post, put } from './client'
/** 凭证列表查询参数。 */
export interface ListCredentialsParams {
 /**
 * 'system' / 'project' 与 DB 行 scope 一一对应；'any' 透传给后端
 * 的 `?scope=any`（system ∪ 当前 project_id 全集，UAT
 * 第 3 项 hotfix follow-up，）。
 */
 scope?: ProviderScopeFilter
 spaceId?: string
 includeInactive?: boolean
 isActive?: boolean
}
/** DRF 分页响应形状。 */
interface DrfPaginated<T> {
 count?: number
 next?: string | null
 previous?: string | null
 results?: T
}
/** 兼容 DRF 分页与裸 list 两种响应。 */
function extractList<T>(payload: T | DrfPaginated<T>): T {
 if (Array.isArray(payload))
 return payload
 return payload.results ??
}
/**
 * 把 ListCredentialsParams 映射成 `client.get` 所需的 params 对象(snake_case)。
 *
 * 后端 query_params 约定:
 * - `scope` = 'system' | 'project' | 'any'（'any' 与 space_id 一起返 system ∪ 当前空间）
 * - `space_id` = UUID
 * - `include_inactive` = 'true'（出现即启用）
 * - `is_active` = 'true' | 'false'
 */
function toQueryParams(
 params: ListCredentialsParams,
): Record<string, string | number | undefined> {
 const qp: Record<string, string | number | undefined> = {}
 if (params.scope)
 qp.scope = params.scope
 if (params.spaceId)
 qp.space_id = params.spaceId
 if (params.includeInactive)
 qp.include_inactive = 'true'
 if (typeof params.isActive === 'boolean')
 qp.is_active = String(params.isActive)
 return qp
}
export const providerCredentialsApi = {
 /** GET /api/providers/credentials/（支持 scope / project_id / include_inactive / is_active 过滤）。 */
 list: async (params: ListCredentialsParams = {}): Promise<ProviderCredentialDto> => {
 const resp = await get<ProviderCredentialDto | DrfPaginated<ProviderCredentialDto>>(
 '/providers/credentials/',
 toQueryParams(params),
 )
 return extractList(resp)
 },
 /** GET /api/providers/credentials/<id>/ */
 retrieve: async (id: string): Promise<ProviderCredentialDto> => {
 return get<ProviderCredentialDto>(`/providers/credentials/${id}/`)
 },
 /** POST /api/providers/credentials/ */
 create: async (
 payload: ProviderCredentialCreatePayload,
 ): Promise<ProviderCredentialDto> => {
 return post<ProviderCredentialDto>('/providers/credentials/', payload)
 },
 /** PATCH /api/providers/credentials/<id>/ */
 update: async (
 id: string,
 payload: ProviderCredentialUpdatePayload,
 ): Promise<ProviderCredentialDto> => {
 return patch<ProviderCredentialDto>(`/providers/credentials/${id}/`, payload)
 },
 /** DELETE /api/providers/credentials/<id>/ */
 remove: async (id: string): Promise<void> => {
 await del(`/providers/credentials/${id}/`)
 },
 /**
 * PATCH /api/providers/credentials/<id>/toggle-active/
 *
 * 后端 @action 自动切反 is_active；PATCH 需带 body(即使为空),
 * 避免部分 middleware 对空 PATCH 抛 400。
 */
 toggleActive: async (id: string): Promise<{ is_active: boolean }> => {
 return patch<{ is_active: boolean }>(
 `/providers/credentials/${id}/toggle-active/`,
 {},
 )
 },
 /** POST /api/providers/credentials/<id>/test-connection/（Phase 既有端点）。 */
 testConnection: async (id: string, model?: string): Promise<TestConnectionResponse> => {
 return post<TestConnectionResponse>(
 `/providers/credentials/${id}/test-connection/`,
 model ? { model }: {},
 )
 },
 /** POST /api/providers/credentials/<id>/refresh-models/ */
 refreshModels: async (id: string): Promise<RefreshModelsResponse> => {
 return post<RefreshModelsResponse>(
 `/providers/credentials/${id}/refresh-models/`,
 {},
 )
 },
 /**
 * POST /api/providers/credentials/<id>/set-default/
 *
 * 把该凭证设为同 (scope, scope_id, provider_type) 维度的默认凭证（Quick 问题①）。
 */
 setDefault: async (id: string): Promise<{ is_default: boolean }> => {
 return post<{ is_default: boolean }>(
 `/providers/credentials/${id}/set-default/`,
 {},
 )
 },
 /**
 * POST /api/providers/fetch-models/
 *
 * 无状态拉模型：用未落库的 config（含 api_key/base_url）直接拉取该 Provider
 * 支持的模型清单，供新建凭证表单使用（Quick 问题④）。
 */
 fetchModelsStateless: async (
 payload: FetchModelsStatelessPayload,
 ): Promise<FetchModelsStatelessResponse> => {
 return post<FetchModelsStatelessResponse>('/providers/fetch-models/', payload)
 },
 /** GET /api/providers/claude-code-config/（Claude Code 编码配置 + credential 展示信息）。 */
 getClaudeCodeConfig: async: Promise<ClaudeCodeConfigDto> => {
 return get<ClaudeCodeConfigDto>('/providers/claude-code-config/')
 },
 /** PUT /api/providers/claude-code-config/（写入选定凭证 + 三档模型映射）。 */
 updateClaudeCodeConfig: async (
 payload: ClaudeCodeConfigPayload,
 ): Promise<ClaudeCodeConfigPayload> => {
 return put<ClaudeCodeConfigPayload>('/providers/claude-code-config/', payload)
 },
 /** GET /api/providers/types/（5 Provider 元信息 + credential_schema JSON Schema）。 */
 listProviderTypes: async: Promise<ProviderTypeMetaDto> => {
 return get<ProviderTypeMetaDto>('/providers/types/')
 },
}
export default providerCredentialsApi
