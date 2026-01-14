/**
 * API 客户端 - 基于原生 fetch 的类型安全封装
 */
import type { ApiErrorResponse } from '~/types'
// API 基础 URL，支持环境变量配置
const API_BASE = import.meta.env.VITE_API_BASE || '/api'
/**
 * API 错误类
 */
export class ApiError extends Error {
 constructor(
 public status: number,
 public detail: string,
 ) {
 super(detail)
 this.name = 'ApiError'
 }
}
/**
 * 请求配置选项
 */
interface RequestOptions extends Omit<RequestInit, 'body'> {
 params?: Record<string, string | number | undefined>
 body?: unknown
}
/**
 * 构建带查询参数的 URL
 */
function buildUrl(endpoint: string, params?: Record<string, string | number | undefined>): string {
 const url = new URL(endpoint, window.location.origin)
 url.pathname = `${API_BASE}${endpoint}`
 if (params) {
 Object.entries(params).forEach(([key, value]) => {
 if (value !== undefined) {
 url.searchParams.set(key, String(value))
 }
 })
 }
 return url.toString
}
/**
 * 基础请求方法
 */
async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
 const { params, body, headers: customHeaders, ...init } = options
 const url = buildUrl(endpoint, params)
 const headers: HeadersInit = {
 ...customHeaders,
 }
 // 如果有 body 且不是 FormData，设置 Content-Type 为 JSON
 if (body && !(body instanceof FormData)) {;(headers as Record<string, string>)['Content-Type'] = 'application/json'
 }
 const response = await fetch(url, {
 ...init,
 headers,
 body: body instanceof FormData ? body: body ? JSON.stringify(body): undefined,
 })
 // 处理 204 No Content
 if (response.status === 204) {
 return undefined as T
 }
 // 处理错误响应
 if (!response.ok) {
 let detail = 'Request failed'
 try {
 const error: ApiErrorResponse = await response.json
 detail = error.detail || detail
 } catch {
 // 忽略 JSON 解析错误
 }
 throw new ApiError(response.status, detail)
 }
 return response.json
}
/**
 * GET 请求
 */
export async function get<T>(
 endpoint: string,
 params?: Record<string, string | number | undefined>,
): Promise<T> {
 return request<T>(endpoint, { method: 'GET', params })
}
/**
 * POST 请求
 */
export async function post<T>(
 endpoint: string,
 body?: unknown,
 options?: Omit<RequestOptions, 'body' | 'method'>,
): Promise<T> {
 return request<T>(endpoint, { method: 'POST', body, ...options })
}
/**
 * PATCH 请求
 */
export async function patch<T>(endpoint: string, body: unknown): Promise<T> {
 return request<T>(endpoint, { method: 'PATCH', body })
}
/**
 * DELETE 请求
 */
export async function del<T = void>(endpoint: string): Promise<T> {
 return request<T>(endpoint, { method: 'DELETE' })
}
/**
 * 上传文件（multipart/form-data）
 */
export async function upload<T>(endpoint: string, formData: FormData): Promise<T> {
 return request<T>(endpoint, { method: 'POST', body: formData })
}
export default {
 get,
 post,
 patch,
 del,
 upload,
 ApiError,
}