/**
 * ProjectHealthCard 守护测试（P1 大盘健康总览）。
 *
 * 覆盖：feature 四态计数 / 待合并 MR 计数 / 规则化下一步建议分支 / 真实 zh-CN 文案。
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
const listDocsMock = vi.fn()
const rebuildMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: {
    getFeatureList: (...a: unknown[]) => getFeatureListMock(...a),
    listDocs: (...a: unknown[]) => listDocsMock(...a),
    rebuildWorkspace: (...a: unknown[]) => rebuildMock(...a),
  },
}))

const listMrMock = vi.fn()
vi.mock('~/api/mergeRequests', () => ({
  mergeRequestsApi: { list: (...a: unknown[]) => listMrMock(...a) },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../ProjectHealthCard.vue')).default

const PROJECT = {
  id: 'p1',
  name: '示例项目',
  description: '一个示例',
  status: 'developing',
} as any

function mountComp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { project: PROJECT, canManage: true },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

const TREE = [
  {
    kind: 'module',
    name: '登录',
    children: [
      { kind: 'feature', name: 'a', state: 'done', children: [] },
      { kind: 'feature', name: 'b', state: 'in_progress', children: [] },
      { kind: 'feature', name: 'c', state: 'testing', children: [] },
      { kind: 'feature', name: 'd', state: 'todo', children: [] },
    ],
  },
]

describe('projectHealthCard（P1）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('聚合 feature 四态计数与总数', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    listDocsMock.mockResolvedValue([{ sync_status: 'synced' }])
    listMrMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()

    expect(wrapper.find('[data-testid="warroom-stat-total"]').text()).toContain('4')
    expect(wrapper.find('[data-testid="warroom-stat-in_progress"]').text()).toContain('1')
    expect(wrapper.find('[data-testid="warroom-stat-testing"]').text()).toContain('1')
    expect(wrapper.find('[data-testid="warroom-stat-done"]').text()).toContain('1')
    expect(wrapper.find('[data-testid="warroom-stat-todo"]').text()).toContain('1')
  })

  it('待合并 MR 仅计 open', async () => {
    getFeatureListMock.mockResolvedValue([])
    listDocsMock.mockResolvedValue([])
    listMrMock.mockResolvedValue([
      { status: 'open' },
      { status: 'open' },
      { status: 'merged' },
      { status: 'closed' },
    ])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="warroom-stat-mr"]').text()).toContain('2')
  })

  it('下一步建议：有 testing 优先推进验收', async () => {
    getFeatureListMock.mockResolvedValue(TREE)
    listDocsMock.mockResolvedValue([])
    listMrMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="warroom-next-step"]').text())
      .toContain(zhCN.projects.warroom.health.next.testing)
  })

  it('下一步建议：无 feature 时提示补充', async () => {
    getFeatureListMock.mockResolvedValue([])
    listDocsMock.mockResolvedValue([])
    listMrMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="warroom-next-step"]').text())
      .toContain(zhCN.projects.warroom.health.next.noFeature)
  })

  it('canManage 时展示重建按钮', async () => {
    getFeatureListMock.mockResolvedValue([])
    listDocsMock.mockResolvedValue([])
    listMrMock.mockResolvedValue([])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="warroom-rebuild-btn"]').exists()).toBe(true)
  })
})
