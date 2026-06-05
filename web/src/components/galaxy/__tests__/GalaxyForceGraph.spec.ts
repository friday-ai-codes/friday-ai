import type { GalaxyEdge, GalaxyNode } from '~/api/galaxy'
/**
 * — GalaxyForceGraph.vue 组件测试
 * 使用 mock 替换 3d-force-graph 和 THREE，绕过 WebGL 环境限制
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock 3d-force-graph
const mockGraph = {
  width: vi.fn().mockReturnThis(),
  height: vi.fn().mockReturnThis(),
  showNavInfo: vi.fn().mockReturnThis(),
  backgroundColor: vi.fn().mockReturnThis(),
  nodeThreeObject: vi.fn().mockImplementation((fn?: unknown) => {
    if (fn === undefined)
      return vi.fn()
    return mockGraph
  }),
  nodeThreeObjectExtend: vi.fn().mockReturnThis(),
  nodeLabel: vi.fn().mockReturnThis(),
  linkColor: vi.fn().mockReturnThis(),
  linkWidth: vi.fn().mockReturnThis(),
  linkOpacity: vi.fn().mockReturnThis(),
  linkDirectionalParticles: vi.fn().mockReturnThis(),
  linkDirectionalParticleSpeed: vi.fn().mockReturnThis(),
  linkDirectionalParticleColor: vi.fn().mockReturnThis(),
  onNodeHover: vi.fn().mockReturnThis(),
  onNodeClick: vi.fn().mockReturnThis(),
  d3Force: vi.fn().mockReturnThis(),
  warmupTicks: vi.fn().mockReturnThis(),
  cooldownTicks: vi.fn().mockReturnThis(),
  d3VelocityDecay: vi.fn().mockReturnThis(),
  onEngineStop: vi.fn().mockImplementation((cb: () => void) => {
    // 立即调用回调（模拟引擎停止）
    setTimeout(cb, 0)
    return mockGraph
  }),
  graphData: vi.fn().mockImplementation((data?: unknown) => {
    if (data === undefined) {
      // getter 模式：返回当前图数据
      return { nodes: [], links: [] }
    }
    return mockGraph // setter 模式：链式
  }),
  scene: vi.fn().mockReturnValue({
    background: null,
    add: vi.fn(),
  }),
  camera: vi.fn().mockReturnValue({}),
  renderer: vi.fn().mockReturnValue({}),
  controls: vi.fn().mockReturnValue({}),
  cameraPosition: vi.fn().mockReturnThis(),
  _destructor: vi.fn(),
}

// 组件使用 new (ForceGraph3D as any)(el, config)，mock 需要是可 new 的函数
function MockForceGraph3D() {
  return mockGraph
}
vi.mock('3d-force-graph', () => ({
  default: MockForceGraph3D,
}))

// Mock THREE.js（使用 class 语法确保 new 操作符正确工作）
vi.mock('three', () => {
  class ColorMock {
    r = 0; g = 0; b = 0; isColor = true
    constructor(_color?: string) {}
  }
  class SphereGeometryMock { constructor(..._args: unknown[]) {} }
  class RingGeometryMock { constructor(..._args: unknown[]) {} }
  class MeshBasicMaterialMock {
    opacity = 1; transparent = false
    constructor(_params?: object) {}
  }
  class MeshMock {
    material = new MeshBasicMaterialMock()
    add = vi.fn()
    traverse = vi.fn()
    constructor(..._args: unknown[]) {}
  }
  class GroupMock {
    add = vi.fn()
    traverse = vi.fn((fn: (child: object) => void) => { fn(new MeshMock()) })
    constructor() {}
  }
  class BufferGeometryMock {
    setAttribute = vi.fn()
    constructor() {}
  }
  class BufferAttributeMock { constructor(..._args: unknown[]) {} }
  class PointsMaterialMock { constructor(..._args: unknown[]) {} }
  class PointsMock { constructor(..._args: unknown[]) {} }
  class CanvasTextureMock { constructor(..._args: unknown[]) {} }
  class MaterialMock {}

  return {
    Color: ColorMock,
    SphereGeometry: SphereGeometryMock,
    RingGeometry: RingGeometryMock,
    MeshBasicMaterial: MeshBasicMaterialMock,
    Mesh: MeshMock,
    Group: GroupMock,
    BufferGeometry: BufferGeometryMock,
    BufferAttribute: BufferAttributeMock,
    PointsMaterial: PointsMaterialMock,
    Points: PointsMock,
    CanvasTexture: CanvasTextureMock,
    DoubleSide: 2,
    Material: MaterialMock,
  }
})

// Mock ResizeObserver（需要 class 形式的构造函数）
class MockResizeObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  constructor(_callback: ResizeObserverCallback) {}
}
globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver

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

describe('galaxyForceGraph.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  it('挂载时初始化 3d-force-graph 实例（graphData 被调用）', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: {
        nodes: mockNodes,
        edges: mockEdges,
      },
      attachTo: document.body,
    })

    await flushPromises()
    // 验证 graphData 被调用（说明 graph 实例初始化成功）
    expect(mockGraph.graphData).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('初始化时预热 force layout，减少首屏可见抖动', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: {
        nodes: mockNodes,
        edges: mockEdges,
      },
      attachTo: document.body,
    })

    await flushPromises()
    expect(mockGraph.warmupTicks).toHaveBeenCalledWith(80)
    expect(mockGraph.cooldownTicks).toHaveBeenCalledWith(60)
    expect(mockGraph.d3VelocityDecay).toHaveBeenCalledWith(0.45)
    wrapper.unmount()
  })

  it('nodeLabel 优先使用图节点自身 payload，避免 tooltip 空白', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: {
        nodes: mockNodes,
        edges: mockEdges,
      },
      attachTo: document.body,
    })
    await flushPromises()

    const labelCallback = mockGraph.nodeLabel.mock.calls[0]?.[0]
    const html = labelCallback?.({
      id: 'symbol:not-in-props',
      type: 'symbol',
      label: 'FallbackSymbol',
      file_path: 'src/fallback.ts',
      degree: 2,
    })

    expect(html).toContain('FallbackSymbol')
    expect(html).toContain('src/fallback.ts')
    expect(html).toContain('degree: 2')
    wrapper.unmount()
  })

  it('props.nodes 变化时更新 graphData', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: { nodes: mockNodes, edges: mockEdges },
      attachTo: document.body,
    })
    await flushPromises()

    const initialCallCount = mockGraph.graphData.mock.calls.length

    // 更新 props（vue-test-utils 类型推断对 generic prop 不友好，用 cast 绕过）
    await wrapper.setProps({ nodes: [...mockNodes, { ...mockNodes[0], id: 'new-node' }] } as unknown as Record<string, unknown>)
    await flushPromises()

    expect(mockGraph.graphData.mock.calls.length).toBeGreaterThan(initialCallCount)
    wrapper.unmount()
  })

  it('onUnmounted 时调用 graph._destructor', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: { nodes: mockNodes, edges: mockEdges },
      attachTo: document.body,
    })
    await flushPromises()

    wrapper.unmount()
    expect(mockGraph._destructor).toHaveBeenCalled()
  })

  it('emit node-click 正确触发', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: { nodes: mockNodes, edges: mockEdges },
      attachTo: document.body,
    })
    await flushPromises()

    // 获取 onNodeClick 回调并调用
    const clickCallback = mockGraph.onNodeClick.mock.calls[0]?.[0]
    if (clickCallback) {
      clickCallback({ id: 'chunk_registry:uuid-1', type: 'chunk_registry' })
    }

    const emitted = wrapper.emitted('node-click')
    expect(emitted).toBeTruthy()
    if (emitted) {
      expect((emitted[0] as GalaxyNode[])[0].id).toBe('chunk_registry:uuid-1')
    }

    wrapper.unmount()
  })

  it('emit node-hover 防抖后正确触发', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: { nodes: mockNodes, edges: mockEdges },
      attachTo: document.body,
    })
    await flushPromises()

    const hoverCallback = mockGraph.onNodeHover.mock.calls[0]?.[0]
    if (hoverCallback) {
      hoverCallback({ id: 'endpoint:uuid-2', type: 'endpoint' }, null)
    }

    // 防抖前不应 emit
    expect(wrapper.emitted('node-hover')).toBeFalsy()

    // 推进 100ms 防抖时间
    vi.advanceTimersByTime(150)

    expect(wrapper.emitted('node-hover')).toBeTruthy()
    wrapper.unmount()
  })
})

// ============================================================================
// — defineExpose focusNode 测试
// ============================================================================

describe('galaxyForceGraph.expose.focusNode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    // 重置 graphData mock 返回带坐标的节点
    mockGraph.graphData.mockReturnValue({
      nodes: [
        { id: 'symbol:target', x: 10, y: 20, z: 30 },
        { id: 'symbol:other', x: 0, y: 0, z: 0 },
      ],
      links: [],
    })
  })

  it('找到节点时调用 cameraPosition 平滑过渡（1000ms）', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: {
        nodes: [{ id: 'symbol:target', type: 'symbol', label: 'Target', file_path: 'src/t.ts', repository_id: 'r1', line_start: 1, line_end: 5, metadata: {}, degree: 1 }],
        edges: [],
      },
      attachTo: document.body,
    })
    await flushPromises()
    // 仅推进 10ms 触发 engineStop callback（避免 requestAnimationFrame 无限循环）
    vi.advanceTimersByTime(10)
    await flushPromises()

    mockGraph.cameraPosition.mockClear()

    const exposedFocusNode = (wrapper.vm as unknown as { focusNode?: (id: string) => void }).focusNode
    if (typeof exposedFocusNode === 'function') {
      exposedFocusNode('symbol:target')
      expect(mockGraph.cameraPosition).toHaveBeenCalledTimes(1)
      const call = mockGraph.cameraPosition.mock.calls[0]
      expect(call[2]).toBe(1000)
    }
    wrapper.unmount()
  })

  it('未找到节点时不调用 cameraPosition', async () => {
    const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')

    const wrapper = mount(GalaxyForceGraph, {
      props: { nodes: [], edges: [] },
      attachTo: document.body,
    })
    await flushPromises()
    vi.advanceTimersByTime(10)
    await flushPromises()

    mockGraph.cameraPosition.mockClear()

    const exposedFocusNode = (wrapper.vm as unknown as { focusNode?: (id: string) => void }).focusNode
    if (typeof exposedFocusNode === 'function') {
      exposedFocusNode('symbol:nonexistent')
      expect(mockGraph.cameraPosition).not.toHaveBeenCalled()
    }
    wrapper.unmount()
  })
})
