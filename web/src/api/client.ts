/**
 * API 客户端 - 基于原生 fetch 的类型安全封装
 * 支持 JWT 认证和自动 Token 刷新
 */
import type { ApiErrorResponse, RefreshResponse } from '~/types'
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
// ============================================================================
// Token 管理（内存存储）
// ============================================================================
let accessToken: string | null = null
/**
 * 设置 Access Token
 */
export function setAccessToken(token: string | null): void {
 accessToken = token
}
/**
 * 获取 Access Token
 */
export function getAccessToken: string | null {
 return accessToken
}
/**
 * 清除 Access Token
 */
export function clearAccessToken: void {
 accessToken = null
}
// ============================================================================
// Token 刷新机制
// ============================================================================
let isRefreshing = false
let refreshSubscribers: Array<(token: string) => void> =
/**
 * 订阅 Token 刷新完成事件
 */
function subscribeTokenRefresh(callback: (token: string) => void): void {
 refreshSubscribers.push(callback)
}
/**
 * 通知所有订阅者 Token 已刷新
 */
function onTokenRefreshed(token: string): void {
 refreshSubscribers.forEach(callback => callback(token))
 refreshSubscribers =
}
/**
 * 刷新 Token
 */
export async function refreshToken: Promise<string> {
 const response = await fetch(`${API_BASE}/auth/refresh/`, {
 method: 'POST',
 credentials: 'include', // 发送 HttpOnly Cookie
 })
 if (!response.ok) {
 throw new ApiError(response.status, '刷新 Token 失败')
 }
 const data: RefreshResponse = await response.json
 setAccessToken(data.access_token)
 return data.access_token
}
// ============================================================================
// 请求方法
// ============================================================================
/**
 * 请求配置选项
 */
interface RequestOptions extends Omit<RequestInit, 'body'> {
 params?: Record<string, string | number | undefined>
 body?: unknown
 skipAuth?: boolean // 跳过认证（用于登录等接口）
}
/**
 * 构建带查询参数的 URL
 */
function buildUrl(endpoint: string, params?: Record<string, string | number | undefined>): string {
 // 确保路径以 / 结尾（防止 Django 301 重定向）
 const normalizedEndpoint = endpoint.endsWith('/') || endpoint.includes('?')
 ? endpoint: `${endpoint}/`
 const url = new URL(normalizedEndpoint, window.location.origin)
 url.pathname = `${API_BASE}${normalizedEndpoint}`
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
 * 基础请求方法（带 Token 刷新支持）
 */
async function request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
 const { params, body, headers: customHeaders, skipAuth, ...init } = options
 const url = buildUrl(endpoint, params)
 const headers: Record<string, string> = {
 ...(customHeaders as Record<string, string>),
 }
 // 如果有 body 且不是 FormData，设置 Content-Type 为 JSON
 if (body && !(body instanceof FormData)) {
 headers['Content-Type'] = 'application/json'
 }
 // 添加 Authorization 头（除非跳过认证）
 if (!skipAuth && accessToken) {
 headers.Authorization = `Bearer ${accessToken}`
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
 // 处理 403 禁止访问
 if (response.status === 403) {
 let detail = '无权访问'
 try {
 const error: ApiErrorResponse = await response.json
 detail = error.detail || detail
 }
 catch {
 // 忽略 JSON 解析错误
 }
 window.dispatchEvent(new CustomEvent('auth:forbidden', { detail }))
 throw new ApiError(403, detail)
 }
 // 处理 401 未授权 - 尝试刷新 Token
 if (response.status === 401 && !skipAuth && !endpoint.includes('/auth/')) {
 // 如果正在刷新，等待刷新完成后重试
 if (isRefreshing) {
 return new Promise<T>((resolve, reject) => {
 subscribeTokenRefresh(async (newToken) => {
 try {
 // 使用新 Token 重试请求
 headers.Authorization = `Bearer ${newToken}`
 const retryResponse = await fetch(url, {
 ...init,
 headers,
 body: body instanceof FormData ? body: body ? JSON.stringify(body): undefined,
 })
 if (!retryResponse.ok) {
 const error: ApiErrorResponse = await retryResponse.json.catch( => ({ detail: 'Request failed' }))
 reject(new ApiError(retryResponse.status, error.detail || 'Request failed'))
 }
 else if (retryResponse.status === 204) {
 resolve(undefined as T)
 }
 else {
 resolve(retryResponse.json)
 }
 }
 catch (err) {
 reject(err)
 }
 })
 })
 }
 // 开始刷新 Token
 isRefreshing = true
 try {
 const newToken = await refreshToken
 isRefreshing = false
 onTokenRefreshed(newToken)
 // 使用新 Token 重试请求
 headers.Authorization = `Bearer ${newToken}`
 const retryResponse = await fetch(url, {
 ...init,
 headers,
 body: body instanceof FormData ? body: body ? JSON.stringify(body): undefined,
 })
 if (retryResponse.status === 204) {
 return undefined as T
 }
 if (!retryResponse.ok) {
 const error: ApiErrorResponse = await retryResponse.json.catch( => ({ detail: 'Request failed' }))
 throw new ApiError(retryResponse.status, error.detail || 'Request failed')
 }
 return retryResponse.json
 }
 catch {
 isRefreshing = false
 refreshSubscribers =
 // 刷新失败，清除 Token 并触发登出
 clearAccessToken
 // 触发自定义事件，让应用层处理跳转登录
 window.dispatchEvent(new CustomEvent('auth:logout'))
 throw new ApiError(401, '登录已过期，请重新登录')
 }
 }
 // 处理其他错误响应
 if (!response.ok) {
 let detail = 'Request failed'
 try {
 const error: ApiErrorResponse = await response.json
 detail = error.detail || detail
 }
 catch {
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
 * PUT 请求
 */
export async function put<T>(endpoint: string, body: unknown): Promise<T> {
 return request<T>(endpoint, { method: 'PUT', body })
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
 put,
 del,
 upload,
 ApiError,
 setAccessToken,
 getAccessToken,
 clearAccessToken,
 refreshToken,
}
