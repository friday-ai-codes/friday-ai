/**
 * client.ts 401 → 刷新 token → 重试 拦截器回归测试。
 *
 * 重点：/auth/me/ 这个启动期鉴权探针在 access token 过期（401）时
 * 必须触发 /auth/refresh/ 并用新 cookie 重试 —— 否则冷刷新页面直接掉登录。
 * 历史 bug：`!endpoint.includes('/auth/')` 把 /auth/me/ 也排除在刷新之外。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, get, post } from '~/api/client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client — 401 自动刷新拦截器', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('/auth/me/ 拿到 401 → 调 /auth/refresh/ → 用新 cookie 重试 /auth/me/ → 成功', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      if (url.includes('/auth/refresh/'))
        return jsonResponse(200, { detail: 'ok' })
      // 第一次 /auth/me/ → 401，刷新后第二次 → 200
      const meCalls = calls.filter(c => c.includes('/auth/me/')).length
      if (url.includes('/auth/me/'))
        return meCalls === 1 ? jsonResponse(401, { detail: 'expired' }) : jsonResponse(200, { id: 'u1', username: 'admin' })
      return jsonResponse(200, {})
    })
    vi.stubGlobal('fetch', fetchMock)

    const user = await get<{ id: string }>('/auth/me/')

    expect(user.id).toBe('u1')
    // 必须调过一次 refresh
    expect(calls.some(c => c.includes('/auth/refresh/'))).toBe(true)
    // /auth/me/ 被请求了两次（首次 401 + 刷新后重试）
    expect(calls.filter(c => c.includes('/auth/me/')).length).toBe(2)
  })

  it('/auth/refresh/ 自身 401 不再递归刷新（防死循环），直接抛错', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      return jsonResponse(401, { detail: 'refresh expired' })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(post('/auth/refresh/', undefined, { credentials: 'include' }))
      .rejects
      .toBeInstanceOf(ApiError)

    // 仅请求一次 refresh，没有递归再调 refresh
    expect(calls.filter(c => c.includes('/auth/refresh/')).length).toBe(1)
  })

  it('skipAuth 请求拿到 401 时不触发 refresh', async () => {
    const calls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      return jsonResponse(401, { detail: 'public endpoint rejected' })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(get('/auth/setup/status/', undefined, { skipAuth: true }))
      .rejects
      .toBeInstanceOf(ApiError)

    expect(calls.filter(c => c.includes('/auth/refresh/')).length).toBe(0)
  })
})
