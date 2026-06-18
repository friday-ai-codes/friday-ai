/**
 * Phase 09 — 管理员只读会话后台前端 RED 组件 spec（ADMVW-01/02/03）。
 *
 * 钉死 `web/src/pages/admin/conversations.vue` 的行为契约：
 *   - 路由 meta `requiresAdmin: true`（与 admin/users.vue 一致；前端守卫仅 UX 兜底）。
 *   - 挂载后调用 `listAdminConversations` 并把跨用户会话渲染进 DataTable（含 owner 列）。
 *   - 只读语义（ADMVW-02）：渲染结果中**不含**消息输入框 / 发送 / 编辑 / 删除入口。
 *   - 「fork 到我的名下」（ADMVW-03）：触发后调用 `forkAdminConversation`，成功后以
 *     `/chat?conversation=<id>` 形式 router.push（admin 即 owner，走普通 chat 续聊）。
 *
 * 执行约定（Wave 0，RED-first）：
 *   - 生产页面 `pages/admin/conversations.vue` 与 `api/adminConversations.ts` **尚未实现**，
 *     故本 spec 的断言**预期全部 RED**（模块解析失败 / 挂载失败 / 断言失败）。
 *     Wave 2（09-03 前端）落地后转 GREEN。
 *   - spec 自身语法合法、可被 vitest 加载；页面加载放在各 `it` 内（动态 import），
 *     使 describe 结构正常注册，失败收敛为每个用例的 RED。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ============================================================================
// Mock：admin 会话 API + toast/error composable + vue-router
// ============================================================================

const listMock = vi.fn()
const getMock = vi.fn()
const forkMock = vi.fn()
const pushMock = vi.fn()

vi.mock('~/api/adminConversations', () => ({
  listAdminConversations: (...a: unknown[]) => listMock(...a),
  getAdminConversation: (...a: unknown[]) => getMock(...a),
  forkAdminConversation: (...a: unknown[]) => forkMock(...a),
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

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRouter: () => ({ push: pushMock, replace: vi.fn() }),
    useRoute: () => ({ query: {}, params: {}, path: '/admin/conversations' }),
  }
})

// ============================================================================
// Fixtures — 跨用户 admin 会话假数据（含不同 owner）
// ============================================================================

interface AdminConversationListItem {
  id: string
  title: string
  status: string
  message_count: number
  owner: { id: string, username: string, display_name: string } | null
  space_id: string
  created_at: string
  updated_at: string
}

function makeItem(
  overrides: Partial<AdminConversationListItem> = {},
): AdminConversationListItem {
  return {
    id: overrides.id ?? 'conv-1',
    title: overrides.title ?? '需求澄清会话',
    status: overrides.status ?? 'completed',
    message_count: overrides.message_count ?? 5,
    owner: overrides.owner ?? { id: 'u-a', username: 'alice', display_name: 'Alice' },
    space_id: overrides.space_id ?? 'space-1',
    created_at: overrides.created_at ?? '2026-06-01T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-06-02T00:00:00Z',
  }
}

// 页面尚未实现：用 import.meta.glob 懒加载（文件缺失时返回空 map，不触发
// transform-time 解析错误），RED 收敛为各 it 内「loader 不存在 → 抛错」，
// 使 spec 可被 vitest 正常收集；Wave 2 页面落地后 glob 命中即转 GREEN。
const pageModules = import.meta.glob('../conversations.vue')
const rawModules = import.meta.glob('../conversations.vue', {
  query: '?raw',
  import: 'default',
})
const PAGE_KEY = '../conversations.vue'

async function loadPage() {
  const loader = pageModules[PAGE_KEY]
  if (!loader)
    throw new Error('pages/admin/conversations.vue 尚未实现（Wave 0 预期 RED）')
  const mod = (await loader()) as { default: unknown }
  return mod.default as any
}

async function mountPage() {
  const Page = await loadPage()
  return mount(Page, {
    attachTo: document.body,
    global: { stubs: { RouterLink: true } },
  })
}

// ============================================================================
// Tests（Wave 0 预期 RED）
// ============================================================================

describe('/admin/conversations 管理员只读会话后台', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    listMock.mockResolvedValue([
      makeItem({ id: 'conv-a', title: 'Alice 的会话', owner: { id: 'u-a', username: 'alice', display_name: 'Alice' } }),
      makeItem({ id: 'conv-b', title: 'Bob 的会话', owner: { id: 'u-b', username: 'bob', display_name: 'Bob' } }),
    ])
    forkMock.mockResolvedValue({ conversation_id: 'forked-123' })
  })

  it('aDMVW-01：页面声明 requiresAdmin 路由 meta', async () => {
    // 源码层断言（definePage meta 经编译注入，组件模块不可直接读）。
    const rawLoader = rawModules[PAGE_KEY]
    expect(rawLoader).toBeDefined() // Wave 0：页面缺失 → undefined → RED
    const src = (await rawLoader!()) as string
    expect(src).toContain('requiresAdmin')
  })

  it('aDMVW-01：挂载后调用 listAdminConversations 并渲染含 owner 列的表格', async () => {
    const wrapper = await mountPage()
    await flushPromises()

    expect(listMock).toHaveBeenCalled()
    const text = wrapper.text()
    expect(text).toContain('Alice 的会话')
    expect(text).toContain('Bob 的会话')
    // owner 列：跨用户可见性体现为不同 owner 文本
    expect(text.toLowerCase()).toContain('alice')
    expect(text.toLowerCase()).toContain('bob')
    wrapper.unmount()
  })

  it('aDMVW-02：只读 —— 无消息输入框 / 发送 / 编辑 / 删除入口', async () => {
    const wrapper = await mountPage()
    await flushPromises()

    // 无消息输入框
    expect(wrapper.find('textarea').exists()).toBe(false)
    // 无写操作按钮（发送 / 编辑 / 删除）
    const buttonTexts = wrapper.findAll('button').map(b => b.text())
    for (const forbidden of ['发送', '编辑', '删除']) {
      expect(buttonTexts.some(t => t.includes(forbidden))).toBe(false)
    }
    wrapper.unmount()
  })

  it('info：draft（小写）状态渲染「草稿」标签（STATUS_META key 大小写一致）', async () => {
    listMock.mockResolvedValue([
      makeItem({ id: 'conv-draft', title: '草稿会话', status: 'draft' }),
    ])
    const wrapper = await mountPage()
    await flushPromises()

    // 存储值为小写 'draft'；STATUS_META 命中后渲染中文标签「草稿」，
    // 而非回退为原始 status 字符串 'draft'。
    const text = wrapper.text()
    expect(text).toContain('草稿')
    expect(text).not.toContain('draft')
    wrapper.unmount()
  })

  it('aDMVW-03：触发 fork 调用 forkAdminConversation 并跳转 /chat?conversation=<id>', async () => {
    const wrapper = await mountPage()
    await flushPromises()

    const forkBtn = wrapper.findAll('button').find(b =>
      /fork|克隆|复制到我的名下|复制到我名下|复制到自己/i.test(b.text()),
    )
    expect(forkBtn).toBeDefined()

    await forkBtn!.trigger('click')
    await flushPromises()

    expect(forkMock).toHaveBeenCalled()
    expect(pushMock).toHaveBeenCalled()
    const pushArg = pushMock.mock.calls.at(-1)?.[0]
    const serialized = typeof pushArg === 'string' ? pushArg : JSON.stringify(pushArg)
    expect(serialized).toContain('/chat')
    expect(serialized).toContain('conversation=forked-123')
    wrapper.unmount()
  })
})
