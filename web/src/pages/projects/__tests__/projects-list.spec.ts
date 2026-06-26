/**
 * /projects 项目列表页守护测试（UI-01）。
 *
 * 覆盖：筛选栏渲染（真实 zh-CN 文案）/ 空态 / 错误态 / 数据卡片渲染 / 创建入口。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
vi.mock('~/stores/auth', () => ({
  useAuthStore: () => ({ isAdmin: true, user: { id: 'u1' } }),
}))

const listMock = vi.fn()
vi.mock('~/api/projects', () => ({
  projectsApi: { list: (...a: unknown[]) => listMock(...a) },
}))
vi.mock('~/api/spaces', () => ({
  default: { list: vi.fn().mockResolvedValue([{ id: 's1', name: '空间一' }]) },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

function makeProject(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p1',
    space_id: 's1',
    space_name: '空间一',
    name: '登录重构',
    description: '描述',
    status: 'developing',
    feishu_project_key: 'k1',
    feishu_board_url: '',
    feishu_board_id: '',
    created_by_id: null,
    member_count: 3,
    created_at: '2026-06-20T00:00:00Z',
    updated_at: '2026-06-20T00:00:00Z',
    ...overrides,
  }
}

const Page = (await import('../index.vue')).default

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Page, {
    global: {
      plugins: [i18n, [VueQueryPlugin, { queryClient }]],
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
        PageContainer: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('/projects 项目列表页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('渲染筛选栏与创建入口（真实 zh-CN 文案）', async () => {
    listMock.mockResolvedValue([makeProject()])
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.filter.allStatus)
    expect(text).toContain(zhCN.projects.filter.onlyMine)
    expect(text).toContain(zhCN.projects.create)
    expect(wrapper.find('[data-testid="create-project-btn"]').exists()).toBe(true)
  })

  it('数据渲染项目卡片', async () => {
    listMock.mockResolvedValue([makeProject(), makeProject({ id: 'p2', name: '支付重构' })])
    const wrapper = mountPage()
    await flushPromises()
    const cards = wrapper.findAll('[data-testid="project-card"]')
    expect(cards.length).toBe(2)
    expect(wrapper.text()).toContain('登录重构')
    expect(wrapper.text()).toContain('支付重构')
    // 状态徽标真实文案
    expect(wrapper.text()).toContain(zhCN.projects.status.developing)
  })

  it('空态渲染引导文案', async () => {
    listMock.mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.empty)
  })

  it('错误态渲染重试', async () => {
    listMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.loadError)
    expect(wrapper.text()).toContain(zhCN.projects.retry)
  })

  it('localStorage 记忆的所选空间驱动列表查询（space_id 生效）', async () => {
    localStorage.setItem('projects-selected-space', 's1')
    listMock.mockResolvedValue([makeProject()])
    mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalled()
    const calledFilters = listMock.mock.calls.at(-1)?.[0]
    expect(calledFilters).toMatchObject({ space_id: 's1' })
  })

  it('无记忆时默认全部空间（filters 不含 space_id）', async () => {
    listMock.mockResolvedValue([makeProject()])
    mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalled()
    const calledFilters = listMock.mock.calls.at(-1)?.[0] ?? {}
    expect(calledFilters).not.toHaveProperty('space_id')
  })
})
