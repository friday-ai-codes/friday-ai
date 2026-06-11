/**
 * GalaxySigmaGraph 组件接线测试
 *
 * mock useGalaxySigma 引擎，验证组件的 props → 引擎调用与事件 → emit 映射。
 */
import type { GalaxyNode } from '~/api/galaxy'
import type { UseGalaxySigmaOptions } from '~/composables/useGalaxySigma'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const mockEngine = {
  layoutRunning: ref(false),
  init: vi.fn(),
  setGraph: vi.fn(),
  setVisibleTypes: vi.fn(),
  setSelectedNode: vi.fn(),
  focusNode: vi.fn(),
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  resetCamera: vi.fn(),
  runLayout: vi.fn(),
  stopLayout: vi.fn(),
  destroy: vi.fn(),
}

let capturedOptions: UseGalaxySigmaOptions = {}

vi.mock('~/composables/useGalaxySigma', () => ({
  useGalaxySigma: vi.fn((options: UseGalaxySigmaOptions) => {
    capturedOptions = options
    return mockEngine
  }),
}))

function makeNode(overrides: Partial<GalaxyNode> = {}): GalaxyNode {
  return {
    id: 'symbol:1',
    type: 'symbol',
    label: 'myFunc',
    repository_id: 'repo-1',
    file_path: 'src/a.py',
    line_start: 1,
    line_end: 10,
    metadata: {},
    degree: 2,
    ...overrides,
  }
}

async function mountGraph(props: Record<string, unknown> = {}) {
  const GalaxySigmaGraph = (await import('~/components/galaxy/GalaxySigmaGraph.vue')).default
  const wrapper = mount(GalaxySigmaGraph, {
    props: {
      nodes: [makeNode()],
      edges: [],
      ...props,
    },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

describe('galaxySigmaGraph', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEngine.layoutRunning.value = false
    capturedOptions = {}
  })

  it('挂载后初始化引擎并 emit ready', async () => {
    const wrapper = await mountGraph()
    expect(mockEngine.init).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('ready')).toHaveLength(1)
    wrapper.unmount()
  })

  it('nodes 为空时不初始化引擎', async () => {
    const wrapper = await mountGraph({ nodes: [] })
    expect(mockEngine.init).not.toHaveBeenCalled()
    expect(wrapper.emitted('ready')).toBeUndefined()
    wrapper.unmount()
  })

  it('数据更新后调用 setGraph（不重新 init）', async () => {
    const wrapper = await mountGraph()
    await wrapper.setProps({ nodes: [makeNode(), makeNode({ id: 'symbol:2' })] })
    await flushPromises()
    expect(mockEngine.init).toHaveBeenCalledTimes(1)
    expect(mockEngine.setGraph).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('引擎 onNodeClick 回调 → emit node-click 完整节点对象', async () => {
    const wrapper = await mountGraph()
    capturedOptions.onNodeClick?.('symbol:1')
    const emitted = wrapper.emitted('node-click')
    expect(emitted).toHaveLength(1)
    expect((emitted![0][0] as GalaxyNode).label).toBe('myFunc')
    wrapper.unmount()
  })

  it('引擎 onNodeHover(null) → emit node-hover null', async () => {
    const wrapper = await mountGraph()
    capturedOptions.onNodeHover?.(null)
    expect(wrapper.emitted('node-hover')![0][0]).toBeNull()
    wrapper.unmount()
  })

  it('activeNodeTypes 变化 → setVisibleTypes', async () => {
    const wrapper = await mountGraph()
    mockEngine.setVisibleTypes.mockClear()
    await wrapper.setProps({ activeNodeTypes: new Set(['symbol']) })
    expect(mockEngine.setVisibleTypes).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('selectedNodeId 变化 → setSelectedNode', async () => {
    const wrapper = await mountGraph()
    await wrapper.setProps({ selectedNodeId: 'symbol:1' })
    expect(mockEngine.setSelectedNode).toHaveBeenCalledWith('symbol:1')
    wrapper.unmount()
  })

  it('expose 的 focusNode 透传到引擎', async () => {
    const wrapper = await mountGraph()
    const vm = wrapper.vm as unknown as { focusNode: (id: string) => void }
    vm.focusNode('symbol:1')
    expect(mockEngine.focusNode).toHaveBeenCalledWith('symbol:1')
    wrapper.unmount()
  })

  it('布局运行时显示提示', async () => {
    const wrapper = await mountGraph()
    expect(wrapper.text()).not.toContain('布局优化中')
    mockEngine.layoutRunning.value = true
    await flushPromises()
    expect(wrapper.text()).toContain('布局优化中')
    wrapper.unmount()
  })
})
