/**
 * Prompts API 服务
 *
 * 覆盖 Phase 的 9 个 REST 端点（server/prompts/urls.py）：
 * - GET /api/prompts/
 * - POST /api/prompts/
 * - GET /api/prompts/{id}/
 * - PATCH /api/prompts/{id}/
 * - DELETE /api/prompts/{id}/
 * - POST /api/prompts/{id}/preview/
 * - GET /api/prompts/{id}/versions/
 * - GET /api/prompts/{id}/versions/{v1}/diff/{v2}/ (由 Plan 使用；本文件已预留函数)
 * - POST /api/prompts/{id}/activate/{version_id}/
 */
import type {
 PromptCategory,
 PromptCreateInput,
 PromptDetail,
 PromptListItem,
 PromptScope,
 PromptUpdateInput,
 PromptVariableMissingPayload,
 PromptVersion,
} from '~/types/prompts'
import { ApiError, del, get, patch, post } from './client'
// ============================================================================
// PromptVariableMissingError
// ============================================================================
/**
 * PromptVariableMissingError —— 为 preview 端点 422 响应专门定义的错误类型。
 *
 * 为什么不复用 ApiError？`ApiError` 只保留 `detail` 字符串
 * （web/src/api/client.ts:14-22），不保留响应 body。而 `PromptVariableForm` 需要从
 * `missing: string` 数组做 inline 高亮，必须保留结构化字段。
 * 方案 A（RESEARCH §R7 推荐）：本文件单独捕获 422 并重新 fetch 以读取完整 body，
 * 避免污染全局 `ApiError` 契约。
 *
 * 同步约束：此错误类字段结构对应后端 server/prompts/views.py:65-75 的
 * `_handle_prompt_error`。若后端字面结构改动必须同步此类与
 * web/src/api/__tests__/__fixtures__/prompt-preview-error.json。
 */
export class PromptVariableMissingError extends Error {
 constructor(
 public readonly slug: string,
 public readonly missing: string,
 ) {
 super(`prompt_variable_missing: ${missing.join(', ')}`)
 this.name = 'PromptVariableMissingError'
 }
}
// ============================================================================
// List 参数（与 server/prompts/views.py:PromptListView 的 queryset 过滤条件对齐）
// ============================================================================
interface ListParams {
 scope: PromptScope
 category?: PromptCategory
 space_id?: string
}
// ============================================================================
// 9 个端点函数（命名与 server/prompts/urls.py 路由一一对应）
// ============================================================================
async function list(params: ListParams): Promise<PromptListItem> {
 // 显式构建 query 对象，避免 `as` 强转逃逸类型检查
 const query: Record<string, string | undefined> = {
 scope: params.scope,
 category: params.category,
 space_id: params.space_id,
 }
 return get<PromptListItem>('/prompts/', query)
}
async function getOne(id: string): Promise<PromptDetail> {
 return get<PromptDetail>(`/prompts/${id}/`)
}
async function create(data: PromptCreateInput): Promise<PromptDetail> {
 return post<PromptDetail>('/prompts/', data)
}
async function update(id: string, data: PromptUpdateInput): Promise<PromptDetail> {
 return patch<PromptDetail>(`/prompts/${id}/`, data)
}
async function remove(id: string): Promise<void> {
 return del<void>(`/prompts/${id}/`)
}
/**
 * 预览渲染 —— 对 422 响应做特殊处理，抛 PromptVariableMissingError 供 UI inline 高亮。
 * 其他状态（200/404/500）沿用 client.ts 默认 ApiError 流。
 */
async function preview(
 id: string,
 variables: Record<string, string>,
): Promise<{ rendered: string }> {
 try {
 return await post<{ rendered: string }>(`/prompts/${id}/preview/`, { variables })
 }
 catch (e) {
 if (e instanceof ApiError && e.status === 422) {
 // client.ts 在 non-2xx 时把 response.json 的 detail 字段丢进 ApiError.detail，
 // missing 数组会丢失。此处绕开 client 封装直接 fetch 读完整 body。
 // preview 是幂等纯查询（无 DB 副作用），double-call 安全。
 throw await fetchPreviewDirect(id, variables)
 }
 throw e
 }
}
async function fetchPreviewDirect(
 id: string,
 variables: Record<string, string>,
): Promise<Error> {
 const API_BASE = import.meta.env.VITE_API_BASE || '/api'
 const resp = await fetch(`${API_BASE}/prompts/${id}/preview/`, {
 method: 'POST',
 credentials: 'include',
 headers: {
 'Content-Type': 'application/json',
 },
 body: JSON.stringify({ variables }),
 })
 if (resp.status === 422) {
 const body = (await resp.json) as PromptVariableMissingPayload
 return new PromptVariableMissingError(body.slug, body.missing)
 }
 // 其他非 422 状态 —— 退回到通用 ApiError
 let detail = 'Request failed'
 try {
 const data = (await resp.json) as { detail?: string }
 detail = data.detail ?? detail
 }
 catch {
 // 忽略 JSON 解析错误
 }
 return new ApiError(resp.status, detail)
}
async function listVersions(id: string): Promise<PromptVersion> {
 return get<PromptVersion>(`/prompts/${id}/versions/`)
}
async function versionDiff(
 id: string,
 v1Num: number,
 v2Num: number,
): Promise<{ diff: string }> {
 return get<{ diff: string }>(`/prompts/${id}/versions/${v1Num}/diff/${v2Num}/`)
}
async function activateVersion(id: string, versionId: string): Promise<PromptDetail> {
 return post<PromptDetail>(`/prompts/${id}/activate/${versionId}/`)
}
// ============================================================================
// 导出（repositories.ts 模式：单一 object 命名空间 + 具名导出）
// ============================================================================
export const promptsApi = {
 list,
 get: getOne,
 create,
 update,
 delete: remove,
 preview,
 listVersions,
 versionDiff,
 activateVersion,
} as const
