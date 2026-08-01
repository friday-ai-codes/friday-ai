/**
 * API 客户端 - 基于原生 fetch 的类型安全封装
 * 认证通过 HTTP-only Cookie 自动处理，前端不管理 token
 */

import type { ApiErrorResponse } from '~/types'

// API 基础 URL，支持环境变量配置
const API_BASE = import.meta.env.VITE_API_BASE || '/api'

/**
 * API 错误类。
 *
 * 扩展：新增可选 `body` 字段携带后端完整 JSON 响应，
 * 用于结构化错误分派（如 preflight 返回 `{code, data}` 时前端需要 data 分支渲染组件）。
 * 构造器签名向后兼容：`body` 参数可选；旧调用点零改动。
 */
export class ApiError extends Error {
  public readonly body: unknown

  constructor(
    public status: number,
    public detail: string,
    body?: unknown,
  ) {
    super(detail)
    this.name = 'ApiError'
    this.body = body
  }
}

// ============================================================================
// Token 刷新机制（前端不存储 token，仅触发后端刷新以更新 cookie）
// ============================================================================

let isRefreshing = false
let refreshSubscribers: Array<() => void> = []

/**
 * 订阅 Token 刷新完成事件
 */
function subscribeTokenRefresh(callback: () => void): void {
  refreshSubscribers.push(callback)
}

/**
 * 通知所有订阅者 Token 已刷新
 */
function onTokenRefreshed(): void {
  refreshSubscribers.forEach(callback => callback())
  refreshSubscribers = []
}

/**
 * 刷新 Token（触发后端更新 HTTP-only cookie）
 */
export async function refreshToken(): Promise<void> {
  const response = await fetch(`${API_BASE}/auth/refresh/`, {
    method: 'POST',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new ApiError(response.status, '刷新 Token 失败')
  }
}

// ============================================================================
// 请求方法
// ============================================================================

/**
 * 请求配置选项
 *
 * `params` 支持基本类型与数组：数组会被多次 append 到 query string，
 * 用于 `symbol_type=FUNCTION&symbol_type=CLASS` 这类 DRF 多值过滤场景。
 */
type QueryParamValue = string | number | boolean | Array<string | number | boolean> | undefined
type QueryParams = Record<string, QueryParamValue>

interface RequestOptions extends Omit<RequestInit, 'body'> {
  params?: QueryParams
  body?: unknown
  skipAuth?: boolean // 跳过认证（用于登录等接口）
}

/**
 * 构建带查询参数的 URL
 */
function buildUrl(endpoint: string, params?: QueryParams): string {
  // 🔴 先把 endpoint 自带的 query 拆出来再拼 pathname。
  // 早先的实现是 `url.pathname = API_BASE + endpoint`，而 `URL.pathname` 的 setter
  // 会把 `?` 百分号编码成 `%3F` —— 于是 `/x/?token=1` 这类调用点发出去的实际路径是
  // `/api/x/%3Ftoken=1`，服务端 404。受影响的是所有把 query 写进路径字面量的调用点
  // （会话运行时轮询的收敛令牌、邀请链接校验）。
  const [rawPath, rawQuery = ''] = endpoint.split('?')
  // 确保路径以 / 结尾（防止 Django 301 重定向）
  const normalizedPath = rawPath.endsWith('/') ? rawPath : `${rawPath}/`

  const url = new URL(`${API_BASE}${normalizedPath}`, window.location.origin)

  if (rawQuery) {
    for (const [key, value] of new URLSearchParams(rawQuery))
      url.searchParams.append(key, value)
  }

  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined)
        return
      if (Array.isArray(value)) {
        value.forEach(v => url.searchParams.append(key, String(v)))
      }
      else {
        url.searchParams.set(key, String(value))
      }
    })
  }

  return url.toString()
}

/**
 * 基础请求方法（带 401 自动刷新支持）
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

  const response = await fetch(url, {
    ...init,
    credentials: 'include',
    headers,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  })

  // 处理 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  // 处理 403 禁止访问
  if (response.status === 403) {
    let detail = '无权访问'
    try {
      const error: ApiErrorResponse = await response.json()
      detail = error.detail || detail
    }
    catch {
      // 忽略 JSON 解析错误
    }
    window.dispatchEvent(new CustomEvent('auth:forbidden', { detail }))
    throw new ApiError(403, detail)
  }

  // 处理 401 未授权 - 尝试刷新 Token。
  //
  // 仅对「认证流」端点跳过刷新（refresh / login / logout）以防死循环：
  // - /auth/refresh/ 自身 401 再去刷新会无限递归；
  // - /auth/login/ 401 是凭据错误，刷新无意义；
  // - /auth/logout/ 不需要刷新。
  //
  // 注意：**不能**笼统排除所有 `/auth/`，否则 `/auth/me/` 这个启动期鉴权探针
  // 在 access token 过期后拿到 401 时不会触发刷新 → 冷刷新页面直接掉登录
  // （HttpOnly refresh cookie 7 天有效却没被用上）。/auth/me/ 必须能触发刷新。
  const isAuthFlowEndpoint = /\/auth\/(?:refresh|login|logout)\b/.test(endpoint)
  if (response.status === 401 && !skipAuth && !isAuthFlowEndpoint) {
    // 如果正在刷新，等待刷新完成后重试
    if (isRefreshing) {
      return new Promise<T>((resolve, reject) => {
        subscribeTokenRefresh(async () => {
          try {
            const retryResponse = await fetch(url, {
              ...init,
              credentials: 'include',
              headers,
              body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
            })

            if (!retryResponse.ok) {
              const error: ApiErrorResponse = await retryResponse.json().catch(() => ({ detail: '请求失败' }))
              reject(new ApiError(retryResponse.status, error.detail || '请求失败'))
            }
            else if (retryResponse.status === 204) {
              resolve(undefined as T)
            }
            else {
              resolve(retryResponse.json())
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
      await refreshToken()
      isRefreshing = false
      onTokenRefreshed()

      // 使用更新后的 cookie 重试请求
      const retryResponse = await fetch(url, {
        ...init,
        credentials: 'include',
        headers,
        body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      })

      if (retryResponse.status === 204) {
        return undefined as T
      }

      if (!retryResponse.ok) {
        const error: ApiErrorResponse = await retryResponse.json().catch(() => ({ detail: '请求失败' }))
        throw new ApiError(retryResponse.status, error.detail || '请求失败')
      }

      return retryResponse.json()
    }
    catch {
      isRefreshing = false
      refreshSubscribers = []
      // 刷新失败，触发登出
      window.dispatchEvent(new CustomEvent('auth:logout'))
      throw new ApiError(401, '登录已过期，请重新登录')
    }
  }

  // 处理其他错误响应
  if (!response.ok) {
    let detail = '请求失败'
    let body_: unknown = null
    try {
      const parsed: ApiErrorResponse & Record<string, unknown> = await response.json()
      body_ = parsed
      detail = (parsed as ApiErrorResponse).detail || detail
    }
    catch {
      // 忽略 JSON 解析错误
    }
    throw new ApiError(response.status, detail, body_)
  }

  return response.json()
}

/**
 * GET 请求
 */
export async function get<T>(
  endpoint: string,
  params?: QueryParams,
  options?: Omit<RequestOptions, 'params' | 'method'>,
): Promise<T> {
  return request<T>(endpoint, { method: 'GET', params, ...options })
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
  refreshToken,
}
