import type { GalaxyEdge, GalaxyNode } from '~/api/galaxy'
/**
 * — EchartsGraphGl.vue 组件测试
 * 注意：EChartsGraphGl 使用动态 import 链初始化，测试重点在接口契约和组件生命周期，
 * 不对 ECharts 内部实现做深度断言
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock echarts 动态 import 链（静态 mock，避免 clearAllMocks 问题）
vi.mock('echarts/core', () => {
  const mockInstance = {
    setOption: vi.fn(),
    on: vi.fn(),
    dispose: vi.fn(),
    resize: vi.fn(),
  }
  return {
    use: vi.fn(),
    init: vi.fn(() => mockInstance),
    __mockInstance: mockInstance,
  }
})

vi.mock('echarts/renderers', () => ({
  CanvasRenderer: {},
}))

vi.mock('echarts/charts', () => ({
  GraphChart: {},
}))

vi.mock('echarts/components', () => ({
  TooltipComponent: {},
  LegendComponent: {},
}))

const mockNodes: GalaxyNode[] = [
  {
    id: 'chunk_registry:uuid-1',
    type: 'chunk_registry',
    label: 'src/foo.py:0',
    repository_id: 'repo-1',
    file_path: 'src/foo.py',
    line_start: 1,
    line_end: 50,
    metadata: {},
    degree: 5,
  },
  {
    id: 'endpoint:uuid-2',
    type: 'endpoint',
    label: 'GET /api/users/',
    repository_id: 'repo-1',
    file_path: 'src/views.py',
    line_start: 10,
    line_end: 30,
    metadata: {},
    degree: 8,
  },
]

const mockEdges: GalaxyEdge[] = [
  {
    id: 'edge-1',
    source: 'chunk_registry:uuid-1',
    target: 'endpoint:uuid-2',
    edge_type: 'API_CALLS',
    weight: 0.9,
    repository_id: 'repo-1',
    target_repository_id: 'repo-2',
    metadata: {},
  },
]

describe('echartsGraphGl.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('挂载成功，不抛出错误，渲染容器 div', async () => {
    const { default: EchartsGraphGl } = await import('../EchartsGraphGl.vue')

    const wrapper = mount(EchartsGraphGl, {
      props: { nodes: mockNodes, edges: mockEdges },
      attachTo: document.body,
    })

    await flushPromises()

    // 验证组件正确渲染（容器 div 存在）
    expect(wrapper.find('div').exists()).toBe(true)
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('接受 loading=true props，显示 loading overlay', async () => {
    const { default: EchartsGraphGl } = await import('../EchartsGraphGl.vue')

    const wrapper = mount(EchartsGraphGl, {
      props: { nodes: [], edges: [], loading: true },
      attachTo: document.body,
    })

    await flushPromises()

    expect(wrapper.text()).toContain('加载 Galaxy 图谱')
    wrapper.unmount()
  })

  it('onUnmounted 后组件不存在（unmount 不抛错）', async () => {
    const { default: EchartsGraphGl } = await import('../EchartsGraphGl.vue')

    const wrapper = mount(EchartsGraphGl, {
      props: { nodes: mockNodes, edges: mockEdges },
      attachTo: document.body,
    })
    await flushPromises()

    expect(() => wrapper.unmount()).not.toThrow()
    expect(wrapper.exists()).toBe(false)
  })
})
