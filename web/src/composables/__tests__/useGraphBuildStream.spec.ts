/**
 * useGraphBuildStream — 4 条核心断言
 *
 * 1. progress 帧解析正确（GraphPayload 9 字段穿透到 onEvent）
 * 2. done 帧解析正确
 * 3. fetch 必带 Bearer header（与 useIndexProgressStream 同款）
 * 4. AbortController.abort() 中断 fetch 时不触发 onError（与 useIndexProgressStream 同款）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { connectGraphProgressStream } from '../useGraphBuildStream'

function makeMockStream(chunks: string[]) {
  let idx = 0
  const encoder = new TextEncoder()
  const reader = {
    read: vi.fn().mockImplementation(() => {
      if (idx >= chunks.length)
        return Promise.resolve({ done: true, value: undefined })
      return Promise.resolve({ done: false, value: encoder.encode(chunks[idx++]) })
    }),
    releaseLock: vi.fn(),
  }
  return {
    ok: true,
    status: 200,
    body: { getReader: () => reader },
  } as unknown as Response
}

describe('useGraphBuildStream', () => {
  let originalFetch: typeof globalThis.fetch
  let originalLocalStorage: Storage

  beforeEach(() => {
    originalFetch = globalThis.fetch
    originalLocalStorage = globalThis.localStorage
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

  it('1: 解析 progress 帧 — onEvent 收到 GraphPayload 9 字段', async () => {
    const onEvent = vi.fn()
    const fetchSpy = vi.fn().mockResolvedValue(makeMockStream([
      'data: {"type":"progress","ts":"2026-05-18T00:00:00Z","graph":{"status":"running","stage":"parse","files_processed":10,"files_total":100,"percent":10,"current_file":"a.py","started_at":"2026-05-18T00:00:00Z","edge_count_so_far":42,"error_message":""}}\n\n',
    ]))
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch

    const ctrl = connectGraphProgressStream('r1', { onEvent })
    // 等待 microtask + 一个 macrotask 处理 stream
    await new Promise(resolve => setTimeout(resolve, 30))
    ctrl.abort()

    expect(onEvent).toHaveBeenCalledTimes(1)
    const arg = onEvent.mock.calls[0][0]
    expect(arg.type).toBe('progress')
    expect(arg.ts).toBe('2026-05-18T00:00:00Z')
    expect(arg.graph.status).toBe('running')
    expect(arg.graph.stage).toBe('parse')
    expect(arg.graph.files_processed).toBe(10)
    expect(arg.graph.files_total).toBe(100)
    expect(arg.graph.percent).toBe(10)
    expect(arg.graph.current_file).toBe('a.py')
    expect(arg.graph.edge_count_so_far).toBe(42)
    expect(arg.graph.error_message).toBe('')
  })

  it('2: 解析 done 帧 — onEvent 收到 { type: done, reason }', async () => {
    const onEvent = vi.fn()
    const fetchSpy = vi.fn().mockResolvedValue(makeMockStream([
      'data: {"type":"done","reason":"idle"}\n\n',
    ]))
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch

    const ctrl = connectGraphProgressStream('r1', { onEvent })
    await new Promise(resolve => setTimeout(resolve, 30))
    ctrl.abort()

    expect(onEvent).toHaveBeenCalledWith({ type: 'done', reason: 'idle' })
  })

  it('3: 带 access_token 时 fetch 必带 Authorization: Bearer + 端点 URL 正确', async () => {
    localStorage.setItem('access_token', 'TEST_JWT')
    const fetchSpy = vi.fn().mockResolvedValue(makeMockStream([]))
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch

    const ctrl = connectGraphProgressStream('repo-42', { onEvent: vi.fn() })
    await Promise.resolve()
    await Promise.resolve()
    ctrl.abort()

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/repositories/repo-42/codegraph/stream/')
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer TEST_JWT')
    expect(headers.Accept).toBe('text/event-stream')
  })

  it('4: controller.abort() 中断 fetch — onError 不应被调用', async () => {
    const fetchSpy = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_, reject) => {
        init.signal!.addEventListener('abort', () => {
          const err = new Error('aborted') as Error & { name: string }
          err.name = 'AbortError'
          reject(err)
        })
      })
    })
    globalThis.fetch = fetchSpy as unknown as typeof globalThis.fetch
    const onError = vi.fn()
    const ctrl = connectGraphProgressStream('r1', { onEvent: vi.fn(), onError })
    // 等待 fetch 挂起
    await Promise.resolve()
    ctrl.abort()
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(onError).not.toHaveBeenCalled()
  })
})
