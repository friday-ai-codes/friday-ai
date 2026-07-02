/**
 * FeatureBoard 守护测试（P1 Feature 大盘）。
 *
 * 覆盖：模块 → 功能点层级渲染 / 状态指示灯与顶部图例 / 空态。
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
  projectWorkspaceApi: {
    getFeatureList: (...a: unknown[]) => getFeatureListMock(...a),
    getFeatureListDraft: vi.fn().mockResolvedValue({ has_draft: false, status: 'idle' }),
  },
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

  it('按模块 → 功能点层级渲染', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="feature-module-view"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="feature-row"]').length).toBe(2)
    const text = wrapper.text()
    expect(text).toContain('登录模块')
    expect(text).toContain('账密登录')
    expect(text).toContain('短信登录')
  })

  it('功能点行展示状态指示灯，顶部展示图例', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="feature-state-legend"]').exists()).toBe(true)
    const dots = wrapper.findAll('[data-testid="feature-state-dot"]')
    expect(dots.length).toBe(2)
    // 状态只用圆点表达：行内不再出现状态文字（图例中出现一次）。
    expect(dots[0].attributes('class')).toContain('rounded-full')
  })

  it('空态渲染真实 zh-CN 文案', async () => {
    getFeatureListMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.workbench.feature.emptyTitle)
  })
})
