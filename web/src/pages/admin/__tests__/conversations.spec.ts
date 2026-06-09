/**
 * Phase 09 — 管理员只读会话管理页 RED 组件 spec（ADMVW-01/02）。
 *
 * 钉死前端契约：`~/pages/admin/conversations.vue`
 *   - 路由 meta `requiresAdmin: true`（与 admin/users.vue 一致，仅 UX 兜底）。
 *   - 挂载后调用 listAdminConversations 并渲染表格行（含 owner 列文本）。
 *   - 只读语义：无消息输入框 / 发送按钮 / 编辑 / 删除入口。
 *   - 「fork 到我的名下」动作：触发后调用 forkAdminConversation 并以
 *     `/chat?conversation=<id>` 形式 router.push（恢复键名见 chat store
 *     restoreFromURL，确认为 `conversation`）。
 *
 * 执行约定（Wave 0，RED-first）：
 *   - `conversations.vue` 尚不存在 → 动态 import 在测试体内 reject / 空源串，
 *     断言失败 → **预期全部 RED**；Wave 2（09-03 前端）落地后转 GREEN。
 *   - 顶层不静态 import 该页面，保证本 spec 文件可被 vitest 加载（语法合法）。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ============================================================================
// Mock：admin 会话 API + composables + router
// ============================================================================

const listAdminConversationsMock = vi.fn()
const forkAdminConversationMock = vi.fn()
const getAdminConversationMock = vi.fn()

vi.mock('~/api/adminConversations', () => ({
  listAdminConversations: (...a: unknown[]) => listAdminConversationsMock(...a),
  getAdminConversation: (...a: unknown[]) => getAdminConversationMock(...a),
  forkAdminConversation: (...a: unknown[]) => forkAdminConversationMock(...a),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const routerPushMock = vi.fn()
vi.mock('vue-router', async (orig) => {
  const actual = await orig<typeof import('vue-router')>().catch(() => ({}))
  return {
    ...actual,
    useRouter: () => ({ push: routerPushMock }),
    useRoute: () => ({ query: {}, params: {} }),
  }
})

// ============================================================================
// Fixtures
// ============================================================================

function makeAdminConversation(overrides: Record<string, unknown> = {}) {
  return {
    id: (overrides.id as string) ?? 'conv-1',
    title: (overrides.title as string) ?? 'A 的会话',
    status: (overrides.status as string) ?? 'completed',
    message_count: (overrides.message_count as number) ?? 3,
    owner: (overrides.owner as unknown) ?? {
      id: 'user-a',
      username: 'alice',
      display_name: 'Alice',
    },
    space_id: (overrides.space_id as string) ?? 'space-1',
    created_at: (overrides.created_at as string) ?? '2026-06-01T00:00:00Z',
    updated_at: (overrides.updated_at as string) ?? '2026-06-02T00:00:00Z',
  }
}

const MOUNT_OPTS = {
  global: { stubs: { RouterLink: true } },
} as const

// 动态拼接 specifier + @vite-ignore：避免 vite 在 transform 期静态解析缺失模块
// 导致整 suite 加载失败（Wave 0 页面尚不存在）。运行时 import reject → 用例
// 各自 RED；09-03 落地后命中真实模块转 GREEN。
const PAGE_PATH = '../conversations.vue'

async function loadPage() {
  const mod = await import(/* @vite-ignore */ PAGE_PATH)
  return mod.default
}

async function loadPageSource(): Promise<string> {
  const rawPath = `${PAGE_PATH}?raw`
  return import(/* @vite-ignore */ rawPath)
    .then((m: { default: string }) => m.default)
    .catch(() => '')
}

// ============================================================================
// Tests
// ============================================================================

describe('admin/conversations.vue（ADMVW-01/02 RED 契约）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    listAdminConversationsMock.mockResolvedValue([
      makeAdminConversation({ id: 'conv-1', title: 'A 的会话', owner: { id: 'user-a', username: 'alice', display_name: 'Alice' } }),
      makeAdminConversation({ id: 'conv-2', title: 'B 的会话', owner: { id: 'user-b', username: 'bob', display_name: 'Bob' } }),
    ])
    forkAdminConversationMock.mockResolvedValue({ conversation_id: 'forked-99' })
  })

  it('页面源码声明 requiresAdmin meta（路由守卫兜底）', async () => {
    const src = await loadPageSource()
    expect(src).toContain('requiresAdmin')
  })

  it('挂载后调用 listAdminConversations 并渲染含 owner 的表格行', async () => {
    const Page = await loadPage()
    const wrapper = mount(Page, MOUNT_OPTS)
    await flushPromises()

    expect(listAdminConversationsMock).toHaveBeenCalled()
    const text = wrapper.text()
    expect(text).toContain('A 的会话')
    // owner 列文本（跨用户可见，ADMVW-01）
    expect(text).toContain('Alice')
    expect(text).toContain('Bob')
  })

  it('只读语义：不含消息输入框 / 发送 / 编辑 / 删除入口', async () => {
    const Page = await loadPage()
    const wrapper = mount(Page, MOUNT_OPTS)
    await flushPromises()

    const html = wrapper.html()
    // 无消息输入框（textarea）
    expect(wrapper.find('textarea').exists()).toBe(false)
    // 无发送 / 编辑 / 删除文案入口
    expect(html).not.toContain('发送')
    expect(html).not.toContain('删除')
    expect(html).not.toContain('编辑')
  })

  it('fork 到我的名下 → 调用 forkAdminConversation 并 router.push(/chat?conversation=<id>)', async () => {
    const Page = await loadPage()
    const wrapper = mount(Page, MOUNT_OPTS)
    await flushPromises()

    const forkBtn = wrapper.findAll('button').find(b => b.text().includes('fork') || b.text().includes('我的名下'))
    expect(forkBtn).toBeDefined()
    await forkBtn!.trigger('click')
    await flushPromises()

    expect(forkAdminConversationMock).toHaveBeenCalled()
    expect(routerPushMock).toHaveBeenCalledWith('/chat?conversation=forked-99')
  })
})
