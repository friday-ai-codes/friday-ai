/**
 * FeatureListSection 守护测试（WB-02）。
 *
 * 覆盖：模块 → 功能点 → 验收项 三层树渲染 / 四态进度灯 class + zh-CN 文案 / 空态 / 错误态重试。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

const getFeatureListMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: {
    getFeatureList: (...a: unknown[]) => getFeatureListMock(...a),
  },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../FeatureListSection.vue')).default

function mountSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function makeTree() {
  return [
    {
      kind: 'module',
      name: '登录模块',
      children: [
        {
          kind: 'feature',
          name: '账号密码登录',
          state: 'in_progress',
          status_display_name: '进行中',
          children: [
            { kind: 'acceptance', name: '错误密码提示' },
            { kind: 'acceptance', name: '记住登录态' },
          ],
        },
        { kind: 'feature', name: '短信登录', state: 'todo', children: [] },
        { kind: 'feature', name: '扫码登录', state: 'testing', children: [] },
        { kind: 'feature', name: '退出登录', state: 'done', children: [] },
      ],
    },
  ]
}

describe('FeatureListSection（WB-02 feature 树 + 进度灯）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('渲染模块 → 功能点 → 验收项 三层树', async () => {
    getFeatureListMock.mockResolvedValue(makeTree())
    const wrapper = mountSection()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="feature-module"]').length).toBe(1)
    expect(wrapper.findAll('[data-testid="feature-item"]').length).toBe(4)
    expect(wrapper.findAll('[data-testid="feature-acceptance"]').length).toBe(2)
    const text = wrapper.text()
    expect(text).toContain('登录模块')
    expect(text).toContain('账号密码登录')
    expect(text).toContain('错误密码提示')
  })

  it('四态进度灯：class 与 zh-CN 文案正确点亮', async () => {
    getFeatureListMock.mockResolvedValue(makeTree())
    const wrapper = mountSection()
    await flushPromises()

    const todo = wrapper.get('[data-testid="feature-state-todo"]')
    const inProgress = wrapper.get('[data-testid="feature-state-in_progress"]')
    const testing = wrapper.get('[data-testid="feature-state-testing"]')
    const done = wrapper.get('[data-testid="feature-state-done"]')

    expect(todo.classes()).toContain('bg-muted')
    expect(inProgress.classes()).toContain('bg-primary/15')
    expect(testing.classes()).toContain('bg-amber-500/15')
    expect(done.classes()).toContain('bg-emerald-500/15')

    expect(todo.text()).toContain(zhCN.projects.workbench.feature.state.todo)
    expect(inProgress.text()).toContain(zhCN.projects.workbench.feature.state.in_progress)
    expect(testing.text()).toContain(zhCN.projects.workbench.feature.state.testing)
    expect(done.text()).toContain(zhCN.projects.workbench.feature.state.done)
  })

  it('空态渲染 zh-CN 文案', async () => {
    getFeatureListMock.mockResolvedValue([])
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.workbench.feature.emptyTitle)
    expect(wrapper.findAll('[data-testid="feature-module"]').length).toBe(0)
  })

  it('错误态渲染重试', async () => {
    getFeatureListMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.find('[data-testid="feature-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.workbench.feature.loadError)
    expect(wrapper.text()).toContain(zhCN.projects.retry)
  })
})
