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
  projectsApi: { listPaged: (...a: unknown[]) => listMock(...a) },
}))
vi.mock('~/api/spaces', () => ({
  default: { list: vi.fn().mockResolvedValue([{ id: 's1', name: '空间一' }]) },
}))

// WB-05 全局搜索面板：mock 项目内搜索端点（聚合调用）。
const searchMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: { search: (...a: unknown[]) => searchMock(...a) },
}))

// CreateProjectModal 走 '~/api' barrel（projectsApi.create / spacesApi.list）。
const createMock = vi.fn()
vi.mock('~/api', () => ({
  projectsApi: { create: (...a: unknown[]) => createMock(...a) },
  spacesApi: { list: vi.fn().mockResolvedValue([{ id: 's1', name: '空间一' }]) },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

/** 包装成后端分页包（listPaged 响应形状）。 */
function makePage(results: Record<string, unknown>[], total = results.length) {
  return { results, total, limit: 24, offset: 0 }
}

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
    listMock.mockResolvedValue(makePage([makeProject()]))
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.filter.allStatus)
    expect(text).toContain(zhCN.projects.filter.onlyMine)
    expect(text).toContain(zhCN.projects.create)
    expect(wrapper.find('[data-testid="create-project-btn"]').exists()).toBe(true)
  })

  it('数据渲染项目卡片', async () => {
    listMock.mockResolvedValue(makePage([makeProject(), makeProject({ id: 'p2', name: '支付重构' })]))
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
    listMock.mockResolvedValue(makePage([]))
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
    listMock.mockResolvedValue(makePage([makeProject()]))
    mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalled()
    const calledFilters = listMock.mock.calls.at(-1)?.[0]
    expect(calledFilters).toMatchObject({ space_id: 's1' })
  })

  it('无记忆时默认全部空间（filters 不含 space_id）', async () => {
    listMock.mockResolvedValue(makePage([makeProject()]))
    mountPage()
    await flushPromises()
    expect(listMock).toHaveBeenCalled()
    const calledFilters = listMock.mock.calls.at(-1)?.[0] ?? {}
    expect(calledFilters).not.toHaveProperty('space_id')
  })

  it('状态筛选控件渲染（按状态筛选入口存在）', async () => {
    listMock.mockResolvedValue(makePage([makeProject()]))
    const wrapper = mountPage()
    await flushPromises()
    // 状态筛选 trigger 以真实 zh-CN aria-label 暴露
    expect(wrapper.find(`[aria-label="${zhCN.projects.filter.status}"]`).exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.filter.allStatus)
  })

  it('成员筛选：勾选「仅我参与」驱动 filters.member', async () => {
    listMock.mockResolvedValue(makePage([makeProject()]))
    const wrapper = mountPage()
    await flushPromises()
    // reka-ui Checkbox 渲染为 button[role=checkbox]，点击切换 v-model。
    const checkbox = wrapper.find('[data-testid="only-mine-checkbox"]')
    expect(checkbox.exists()).toBe(true)
    await checkbox.trigger('click')
    await flushPromises()
    const calledFilters = listMock.mock.calls.at(-1)?.[0] ?? {}
    expect(calledFilters).toMatchObject({ member: 'u1' })
  })

  it('无限滚动：还有下一页时渲染加载哨兵，单页装完则不渲染', async () => {
    // total=30 > 已加载 1 条 → 有下一页，哨兵挂载
    listMock.mockResolvedValue(makePage([makeProject()], 30))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="load-more-sentinel"]').exists()).toBe(true)
    wrapper.unmount()

    // total=1 全部装完 → 无下一页，哨兵不挂载
    listMock.mockResolvedValue(makePage([makeProject()], 1))
    const wrapper2 = mountPage()
    await flushPromises()
    expect(wrapper2.find('[data-testid="load-more-sentinel"]').exists()).toBe(false)
    wrapper2.unmount()
  })

  it('全局搜索：展开面板、搜索结果渲染并标注 repo/project 定位', async () => {
    listMock.mockResolvedValue(makePage([makeProject()]))
    searchMock.mockResolvedValue([
      { text: '命中：登录鉴权改造方案', score: 0.92, locator: '仓库 auth-svc / 登录重构' },
    ])
    const wrapper = mountPage()
    await flushPromises()

    // 默认折叠：先点开全局搜索
    expect(wrapper.find('[data-testid="global-search-panel"]').exists()).toBe(false)
    await wrapper.find('[data-testid="global-search-toggle"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="global-search-panel"]').exists()).toBe(true)

    // 输入关键词并即时触发（回车，避开防抖计时器）
    const input = wrapper.find('[data-testid="global-search-input"]')
    await input.setValue('登录')
    await input.trigger('keyup.enter')
    await flushPromises()

    expect(searchMock).toHaveBeenCalledWith('p1', '登录')
    const results = wrapper.findAll('[data-testid="search-result"]')
    expect(results.length).toBe(1)
    expect(wrapper.text()).toContain('命中：登录鉴权改造方案')
    // locator 定位文案（属于 仓库/项目）
    expect(wrapper.text()).toContain('仓库 auth-svc / 登录重构')
    // RAG 预留位（Phase 85）
    expect(wrapper.find('[data-testid="search-rag-slot"]').exists()).toBe(true)

    wrapper.unmount()
  })

  it('全局搜索：无结果落空态文案「没有匹配的内容」', async () => {
    listMock.mockResolvedValue(makePage([makeProject()]))
    searchMock.mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="global-search-toggle"]').trigger('click')
    await flushPromises()
    const input = wrapper.find('[data-testid="global-search-input"]')
    await input.setValue('不存在的词')
    await input.trigger('keyup.enter')
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.search.emptyTitle)
    wrapper.unmount()
  })
})

describe('CreateProjectModal 创建入口（手动创建 + 绑定看板）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  async function mountModal() {
    const Modal = (await import('~/components/project/CreateProjectModal.vue')).default
    return mount(Modal, {
      global: {
        plugins: [i18n],
        stubs: {
          VueFinalModal: { template: '<div><slot /></div>' },
        },
      },
    })
  }

  it('渲染创建表单与绑定看板字段（飞书看板链接 + 项目 Key）', async () => {
    const wrapper = await mountModal()
    await flushPromises()
    expect(wrapper.text()).toContain('创建项目')
    expect(wrapper.find('[data-testid="bind-board-section"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="feishu-board-url"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="feishu-project-key"]').exists()).toBe(true)
  })

  it('提交手动创建并携带绑定看板字段，成功后 emit confirm(projectId)', async () => {
    createMock.mockResolvedValue({ id: 'new-proj-1' })
    const wrapper = await mountModal()
    await flushPromises()

    // 选择空间 + 填名称 + 绑定看板字段
    await wrapper.find('#space_id').setValue('s1')
    await wrapper.find('#name').setValue('支付重构')
    await wrapper.find('[data-testid="feishu-board-url"]').setValue('https://project.feishu.cn/board/x')
    await wrapper.find('[data-testid="feishu-project-key"]').setValue('pay_key')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock).toHaveBeenCalledWith(expect.objectContaining({
      space_id: 's1',
      name: '支付重构',
      feishu_board_url: 'https://project.feishu.cn/board/x',
      feishu_project_key: 'pay_key',
    }))
    expect(wrapper.emitted('confirm')?.[0]).toEqual(['new-proj-1'])
  })
})
