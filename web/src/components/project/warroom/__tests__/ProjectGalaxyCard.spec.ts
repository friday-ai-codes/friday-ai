/**
 * ProjectGalaxyCard 守护测试（项目作战室 P4）。
 *
 * 覆盖：数据态渲染图例 + 画布容器 / 空态（仅项目节点）/ 错误态重试。
 * 3d-force-graph 以链式 stub mock（happy-dom 无 WebGL）。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('3d-force-graph', () => {
  const chain: any = new Proxy({}, { get: () => () => chain })
  return { default: () => () => chain }
})

const getGalaxyMock = vi.fn()
vi.mock('~/api/projectGalaxy', () => ({
  projectGalaxyApi: { get: (...a: unknown[]) => getGalaxyMock(...a) },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../ProjectGalaxyCard.vue')).default

function mountComp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('projectGalaxyCard（P4）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('数据态渲染图例 + 画布容器', async () => {
    getGalaxyMock.mockResolvedValue({
      nodes: [
        { id: 'project:p1', type: 'project', label: '项目 P' },
        { id: 'mr:1', type: 'merge_request', label: 'MR1', status: 'open' },
      ],
      edges: [{ source: 'project:p1', target: 'mr:1', relation: 'HAS_MR' }],
      meta: { total_nodes: 2, total_edges: 1, truncated: false },
    })
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="galaxy-canvas"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.warroom.galaxy.type.mergeRequest)
  })

  it('空态（仅项目节点）渲染空文案', async () => {
    getGalaxyMock.mockResolvedValue({
      nodes: [{ id: 'project:p1', type: 'project', label: '项目 P' }],
      edges: [],
      meta: { total_nodes: 1, total_edges: 0, truncated: false },
    })
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.warroom.galaxy.emptyTitle)
  })

  it('错误态渲染重试', async () => {
    getGalaxyMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.warroom.galaxy.loadError)
    expect(wrapper.text()).toContain(zhCN.projects.retry)
  })
})
