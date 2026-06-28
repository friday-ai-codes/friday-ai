/**
 * FeatureBoard 守护测试（P1 Feature 视图切换）。
 *
 * 覆盖：按状态分组（含 module_normalized 回填）/ 按模块视图切换 / 空态。
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

const Comp = (await import('../FeatureBoard.vue')).default

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
      { kind: 'feature', name: '账密登录', state: 'done', module_normalized: '登录模块', children: [{ kind: 'acceptance', name: '凭证正确可登录' }] },
      { kind: 'feature', name: '短信登录', state: 'in_progress', children: [] },
    ],
  },
]

describe('featureBoard（P1）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('默认按状态视图渲染分组', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="feature-status-view"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="feature-row"]').length).toBe(2)
    const text = wrapper.text()
    expect(text).toContain('账密登录')
    expect(text).toContain('短信登录')
  })

  it('可切换到按模块视图', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()
    await wrapper.find('[data-testid="feature-view-module"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="feature-module-view"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('登录模块')
  })

  it('空态渲染真实 zh-CN 文案', async () => {
    getFeatureListMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.workbench.feature.emptyTitle)
  })
})
