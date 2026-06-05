/**
 * useIndexProgressStream — SSE 客户端鉴权契约。
 *
 * 关键回归保护：项目走 JWT (Bearer) 鉴权，SSE 端点同 DRF View 一样要 IsAuthenticated。
 * 如果 fetch 没带 Authorization header，会被服务端 401 静默拒绝 — 整个进度流 UI
 * 永远收不到 progress 事件，前端进度条卡在初始 stage（如"克隆仓库中..."）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { connectIndexProgressStream } from '../useIndexProgressStream'

describe('useIndexProgressStream — 鉴权契约', () => {
  let originalFetch: typeof globalThis.fetch
  let originalLocalStorage: Storage

  beforeEach(() => {
    originalFetch = globalThis.fetch
    originalLocalStorage = globalThis.localStorage
    // 简易 in-memory localStorage stub
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => store.set(k, v),
        removeItem: (k: string) => store.delete(k),
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() {
          return store.size
        },
      },
    })
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: originalLocalStorage,
    })
    vi.restoreAllMocks()
  })

  it('localStorage 中有 access_token 时，fetch 必须带 Authorization: Bearer', async () => {
    localStorage.setItem('access_token', 'TEST_JWT_TOKEN')

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => ({ done: true, value: undefined }),
          releaseLock: () => {},
        }),
      },
    } as unknown as Response)
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch

    const ctrl = connectIndexProgressStream('repo-1', { onEvent: () => {} })
    // 等下一个微任务，让 runStream 进入 fetch 调用
    await Promise.resolve()
    await Promise.resolve()
    ctrl.abort()

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const callArgs = fetchSpy.mock.calls[0]
    const url = callArgs[0] as string
    const init = callArgs[1] as RequestInit
    expect(url).toContain('/repositories/repo-1/index/stream/')
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer TEST_JWT_TOKEN')
    expect(headers.Accept).toBe('text/event-stream')
  })

  it('没有 access_token 时不应附带空 Authorization（避免误打成 "Bearer "）', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => ({ done: true, value: undefined }),
          releaseLock: () => {},
        }),
      },
    } as unknown as Response)
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch

    const ctrl = connectIndexProgressStream('repo-2', { onEvent: () => {} })
    await Promise.resolve()
    await Promise.resolve()
    ctrl.abort()

    const init = fetchSpy.mock.calls[0][1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBeUndefined()
  })
})
