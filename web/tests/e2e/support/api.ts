/**
 * e2e 的后端替身：拦截 `**\/api\/**` 并按路径回放固定载荷。
 *
 * 与 `tests/e2e/auth.spec.ts` 同一套模型 —— 只起 Vite dev server，不起 Django。
 * 这些用例要验证的是「给定这份后端载荷，用户在浏览器里能不能看到对的东西」，
 * 载荷形状由后端用例锁定；在这里 mock 才能让整套护栏无副作用、可重复、秒级。
 *
 * 🔴 载荷形状一律照抄真实序列化产物（见 `payloads.ts` 每个 builder 的出处注释），
 * 不自创字段名 —— 形状对不上的 fixture 会产出「绿了但什么都没证明」的用例，
 * 那正是 v0.19.0 里程碑审计点名的失败模式。
 */
import type { Page, Route } from '@playwright/test'

export interface ApiContext {
  route: Route
  method: string
  /** 去掉 `/api` 前缀与结尾斜杠后的路径，例如 `/chat/conversations/c-1/runtime`。 */
  path: string
  url: URL
}

/** 返回 true 表示已处理；返回 false 交给默认表。 */
export type ApiHandler = (ctx: ApiContext) => Promise<boolean> | boolean

export interface ApiCallRecord {
  method: string
  path: string
  /** 相对 `installApi` 调用时刻的毫秒数，用于「是不是等到轮询才更新」这类断言。 */
  at: number
}

export interface ApiMock {
  calls: ApiCallRecord[]
  /** 命中 `path.includes(fragment)` 的调用次数。 */
  countOf: (method: string, fragment: string) => number
}

export const E2E_USER = {
  id: 'u-e2e-1',
  username: 'e2e-admin',
  display_name: 'E2E 管理员',
  is_active: true,
  is_superuser: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export const E2E_SPACE = {
  id: 'sp-1',
  name: 'E2E 空间',
  description: '',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export const E2E_REPOSITORIES = [
  { id: 'r-in', name: 'onion-web', description: '前端主仓', space_id: E2E_SPACE.id },
  { id: 'r-out', name: 'sso-gateway', description: '统一登录网关', space_id: E2E_SPACE.id },
]

/** 与 `ProviderCredentialDto` 对齐的最小可用凭证 —— ChatInput 靠它判定「能不能发消息」。 */
export const E2E_CREDENTIAL = {
  id: 'cred-1',
  name: 'E2E Provider',
  provider_type: 'anthropic',
  scope: 'system',
  space: null,
  is_active: true,
  is_default: true,
  base_url: '',
  default_model: 'claude-e2e',
  available_models: [{ id: 'claude-e2e', display_name: 'claude-e2e' }],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

/** 侧栏会话列表里的那一条 —— 与 `payloads.conversation()` 同 id。 */
export const E2E_CONVERSATION_SUMMARY = {
  id: 'c-e2e-1',
  space_id: E2E_SPACE.id,
  title: 'E2E 会话',
  model: 'claude-e2e',
  status: 'active',
  provider_credential_id: E2E_CREDENTIAL.id,
  bound_project_id: null,
  visibility: 'personal',
  is_archived: false,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
}

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

/**
 * 默认路由表：让 `/chat` 与 `/admin` 能在「已登录 + 有一个空间 + 有一个可用凭证」
 * 的前提下开屏。用例只需覆盖自己关心的那几条。
 */
async function fallback(ctx: ApiContext): Promise<void> {
  const { route, path, method } = ctx

  if (path === '/auth/setup/status')
    return json(route, { needs_setup: false })
  if (path === '/auth/me')
    return json(route, E2E_USER)
  if (path === '/auth/refresh')
    return json(route, {})
  if (path === '/users/me') {
    return json(route, {
      ...E2E_USER,
      email: 'e2e@example.com',
      display_name: E2E_USER.display_name,
      gravatar_url: null,
      space_memberships: [{ space_id: E2E_SPACE.id, space_name: E2E_SPACE.name, role: 'admin' }],
    })
  }
  if (path === '/spaces')
    return json(route, [E2E_SPACE])
  if (path === '/repositories')
    return json(route, E2E_REPOSITORIES)
  if (path === '/providers/credentials')
    return json(route, [E2E_CREDENTIAL])
  if (path === '/providers/types')
    return json(route, [])
  if (path === '/chat/conversations')
    return json(route, [E2E_CONVERSATION_SUMMARY])
  if (path === '/chat/models')
    return json(route, { models: [{ id: 'claude-e2e', name: 'claude-e2e', created: null }] })
  if (path === '/chat/feishu-export-availability')
    return json(route, { available: false, reason: null })
  if (path === '/settings')
    return json(route, [])

  // 兜底：GET 一律回空列表（绝大多数未覆盖端点是列表），写操作回空对象。
  return json(route, method === 'GET' ? [] : {})
}

/**
 * 安装 API 替身 + WebSocket 替身。
 *
 * WebSocket 也要接管：`chatStore.connectRealtime()` 会连 `/ws/chat/`，不接管时
 * 连接失败会触发指数退避重连，在 trace 里制造噪声（不影响断言，但会掩盖真信号）。
 */
export async function installApi(page: Page, handler?: ApiHandler): Promise<ApiMock> {
  const started = Date.now()
  const calls: ApiCallRecord[] = []

  await page.routeWebSocket(/\/ws\//, () => {
    // 建立后不发任何帧：本套用例的实时性全部走 SSE / 轮询两条链，不依赖 ws。
  })

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }
    const method = route.request().method()
    const path = url.pathname.replace(/^\/api/, '').replace(/\/$/, '')
    calls.push({ method, path, at: Date.now() - started })

    const ctx: ApiContext = { route, method, path, url }
    if (handler && await handler(ctx))
      return
    await fallback(ctx)
  })

  return {
    calls,
    countOf: (method, fragment) =>
      calls.filter(c => c.method === method && c.path.includes(fragment)).length,
  }
}

export { json as fulfillJson }
