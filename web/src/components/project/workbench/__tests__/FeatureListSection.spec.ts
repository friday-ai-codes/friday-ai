/**
 * FeatureListSection 守护测试（WB-02）。
 *
 * 覆盖：模块→功能点→验收项 三层树渲染 / 四态进度灯 class+文案 /
 * 折叠交互（aria-expanded）/ 空态真实 zh-CN 文案 / 错误态重试。
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

const getFeatureListMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: { getFeatureList: (...a: unknown[]) => getFeatureListMock(...a) },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../FeatureListSection.vue')).default

function mountComp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

const TREE = [
  {
    kind: 'module',
    name: '登录模块',
    children: [
      { kind: 'feature', name: '账号密码登录', state: 'done', children: [{ kind: 'acceptance', name: '正确凭证可登录' }] },
      { kind: 'feature', name: '短信登录', state: 'in_progress', children: [] },
      { kind: 'feature', name: 'SSO 登录', state: 'testing', children: [] },
      { kind: 'feature', name: '生物识别', state: 'todo', children: [] },
    ],
  },
]

describe('featureListSection（WB-02）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('渲染 模块→功能点→验收项 三层树', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="feature-module"]').length).toBe(1)
    expect(wrapper.findAll('[data-testid="feature-item"]').length).toBe(4)
    expect(wrapper.findAll('[data-testid="feature-acceptance"]').length).toBe(1)
    const text = wrapper.text()
    expect(text).toContain('登录模块')
    expect(text).toContain('账号密码登录')
    expect(text).toContain('正确凭证可登录')
  })

  it('功能点四态进度灯 class + 真实 zh-CN 文案', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()

    const done = wrapper.find('[data-testid="feature-state-done"]')
    expect(done.classes()).toContain('bg-emerald-500/15')
    expect(done.text()).toContain(zhCN.projects.workbench.feature.state.done)

    const running = wrapper.find('[data-testid="feature-state-in_progress"]')
    expect(running.classes()).toContain('bg-primary/15')
    expect(running.text()).toContain(zhCN.projects.workbench.feature.state.in_progress)

    const testing = wrapper.find('[data-testid="feature-state-testing"]')
    expect(testing.classes()).toContain('bg-amber-500/15')
    expect(testing.text()).toContain(zhCN.projects.workbench.feature.state.testing)

    const todo = wrapper.find('[data-testid="feature-state-todo"]')
    expect(todo.classes()).toContain('bg-muted')
    expect(todo.text()).toContain(zhCN.projects.workbench.feature.state.todo)
  })

  it('功能点节点可折叠（aria-expanded 切换）', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()
    const trigger = wrapper.findAll('[data-testid="feature-item"]')[0]
    expect(trigger.attributes('aria-expanded')).toBe('true')
    await trigger.trigger('click')
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
  })

  it('空态渲染真实 zh-CN 文案', async () => {
    getFeatureListMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.workbench.feature.emptyTitle)
  })

  it('错误态渲染重试', async () => {
    getFeatureListMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.workbench.feature.loadError)
    expect(wrapper.text()).toContain(zhCN.projects.retry)
  })
})
