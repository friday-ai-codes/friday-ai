import type { GraphEdge, GraphNode } from '@vue-flow/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

// ---------------------------------------------------------------------------
// C. 被测模块（在 mock 之后导入）
// ---------------------------------------------------------------------------
import { getRecentNodes, useDragAndDrop } from '../useDragAndDrop'

// ---------------------------------------------------------------------------
// A. 对照实现：pointToLineDistance（纯数学函数，零外部依赖）
// ---------------------------------------------------------------------------
function pointToLineDistance(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy

  if (lenSq === 0) {
    return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
  }

  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))

  const closestX = x1 + t * dx
  const closestY = y1 + t * dy

  return Math.sqrt((px - closestX) ** 2 + (py - closestY) ** 2)
}

// ---------------------------------------------------------------------------
// B. Mock 设置
// ---------------------------------------------------------------------------

const mockScreenToFlowCoordinate = vi.fn(({ x, y }: { x: number, y: number }) => ({ x, y }))
const mockEdges = ref<GraphEdge[]>([])
const mockAddNode = vi.fn()
const mockRemoveEdge = vi.fn()
const mockAddEdge = vi.fn()

vi.mock('@vue-flow/core', () => ({
  useVueFlow: () => ({
    screenToFlowCoordinate: mockScreenToFlowCoordinate,
    getEdges: mockEdges,
  }),
}))

vi.mock('~/stores/useWorkflowsStore', () => ({
  useWorkflowsStore: () => ({
    addNode: mockAddNode,
    removeEdge: mockRemoveEdge,
    addEdge: mockAddEdge,
  }),
}))

vi.mock('~/types/workflow/registry', () => ({
  getNodeDefinition: () => ({
    displayName: '测试节点',
    schema: { parse: () => ({}) },
  }),
}))

vi.mock('~/utils/shortId', () => ({
  generateShortId: () => 'abc',
}))

// crypto.randomUUID
interface CryptoMock { randomUUID: () => string }
Object.defineProperty(globalThis, 'crypto', {
  value: { randomUUID: () => 'test-uuid-1234' } as CryptoMock,
  writable: true,
  configurable: true,
})

// localStorage mock
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value },
    clear: () => { store = {} },
  }
})()
Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
  configurable: true,
})

// window.dispatchEvent spy
const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent')

// ---------------------------------------------------------------------------
// D. Fixture 工厂
// ---------------------------------------------------------------------------
function makeGraphNode(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: overrides.id ?? 'node-1',
    position: overrides.position ?? { x: 100, y: 100 },
    computedPosition: overrides.computedPosition ?? { x: 100, y: 100, z: 0 },
    dimensions: overrides.dimensions ?? { width: 200, height: 80 },
    handleBounds: { source: [], target: [] },
    isParent: false,
    selected: false,
    resizing: false,
    dragging: false,
    data: {},
    events: {},
    type: 'default',
    ...overrides,
  } as GraphNode
}

function makeGraphEdge(overrides: Partial<GraphEdge> = {}): GraphEdge {
  const sourceNode = makeGraphNode({ id: overrides.source ?? 'node-a', position: { x: 0, y: 0 } })
  const targetNode = makeGraphNode({ id: overrides.target ?? 'node-b', position: { x: 100, y: 100 } })
  return {
    id: overrides.id ?? 'edge-1',
    source: overrides.source ?? 'node-a',
    target: overrides.target ?? 'node-b',
    sourceX: overrides.sourceX ?? 0,
    sourceY: overrides.sourceY ?? 0,
    targetX: overrides.targetX ?? 100,
    targetY: overrides.targetY ?? 100,
    sourceNode,
    targetNode,
    selected: false,
    data: {},
    events: {},
    type: 'default',
    ...overrides,
  } as GraphEdge
}

function makeDropEvent(data: { nodeType: string, clientX: number, clientY: number, name?: string }): DragEvent {
  const dt = {
    getData: (format: string) => {
      if (format === 'application/vueflow')
        return data.nodeType
      if (format === 'application/vueflow-name')
        return data.name ?? ''
      return ''
    },
    dropEffect: '',
  } as unknown as DataTransfer

  return {
    dataTransfer: dt,
    clientX: data.clientX,
    clientY: data.clientY,
    preventDefault: vi.fn(),
  } as unknown as DragEvent
}

// ---------------------------------------------------------------------------
// E. 测试套件
// ---------------------------------------------------------------------------

describe('pointToLineDistance 对照实现', () => {
  it('点在线段中点（t=0.5）时距离为 0', () => {
    const dist = pointToLineDistance(50, 50, 0, 0, 100, 100)
    expect(dist).toBe(0)
  })

  it('线段退化为点时计算到该点的距离', () => {
    const dist = pointToLineDistance(30, 40, 0, 0, 0, 0)
    expect(dist).toBe(50)
  })

  it('点在线段起点延长线外（t<0）时距离到起点', () => {
    const dist = pointToLineDistance(-10, 0, 0, 0, 100, 0)
    expect(dist).toBe(10)
  })

  it('点在线段终点延长线外（t>1）时距离到终点', () => {
    const dist = pointToLineDistance(110, 0, 0, 0, 100, 0)
    expect(dist).toBe(10)
  })

  it('一般情况（点在线段附近）返回正确最短距离', () => {
    // 线段从 (0,0) 到 (100,0)，点 (50,30)
    const dist = pointToLineDistance(50, 30, 0, 0, 100, 0)
    expect(dist).toBe(30)
  })
})

describe('useDragAndDrop — onDrop', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEdges.value = []
    mockScreenToFlowCoordinate.mockImplementation(({ x, y }: { x: number, y: number }) => ({ x, y }))
    localStorageMock.clear()
    dispatchEventSpy.mockClear()
  })

  it('无 edge 时直接添加节点，调用 store.addNode，不调用 removeEdge', () => {
    const { onDrop } = useDragAndDrop()
    const event = makeDropEvent({ nodeType: 'test-node', clientX: 50, clientY: 50 })

    onDrop(event)

    expect(mockAddNode).toHaveBeenCalledTimes(1)
    expect(mockRemoveEdge).not.toHaveBeenCalled()
    expect(mockAddEdge).not.toHaveBeenCalled()
  })

  it('落点在 edge 上（距离 < EDGE_HIT_TOLERANCE）时：删除原 edge、添加新节点、添加两条新 edge', () => {
    mockEdges.value = [
      makeGraphEdge({
        id: 'edge-a-b',
        source: 'node-a',
        target: 'node-b',
        sourceX: 0,
        sourceY: 0,
        targetX: 100,
        targetY: 0,
      }),
    ]

    const { onDrop } = useDragAndDrop()
    // 点 (50, 10) 到线段 (0,0)-(100,0) 的距离为 10 < 20
    const event = makeDropEvent({ nodeType: 'test-node', clientX: 50, clientY: 10 })

    onDrop(event)

    expect(mockRemoveEdge).toHaveBeenCalledTimes(1)
    expect(mockRemoveEdge).toHaveBeenCalledWith('edge-a-b')

    expect(mockAddNode).toHaveBeenCalledTimes(1)
    const addedNode = mockAddNode.mock.calls[0][0]
    expect(addedNode.id).toBe('test-uuid-1234')
    expect(addedNode.shortId).toBe('abc')
    expect(addedNode.nodeType).toBe('test-node')

    expect(mockAddEdge).toHaveBeenCalledTimes(2)
    const edgeCalls = mockAddEdge.mock.calls.map(c => c[0])
    expect(edgeCalls).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: 'node-a',
          target: 'test-uuid-1234',
          sourcePort: 'default',
          targetPort: 'default',
        }),
        expect.objectContaining({
          source: 'test-uuid-1234',
          target: 'node-b',
          sourcePort: 'default',
          targetPort: 'default',
        }),
      ]),
    )
  })

  it('落点未命中 edge（距离 >= EDGE_HIT_TOLERANCE）时只添加节点', () => {
    mockEdges.value = [
      makeGraphEdge({
        id: 'edge-a-b',
        source: 'node-a',
        target: 'node-b',
        sourceX: 0,
        sourceY: 0,
        targetX: 100,
        targetY: 0,
      }),
    ]

    const { onDrop } = useDragAndDrop()
    // 点 (50, 50) 到线段 (0,0)-(100,0) 的距离为 50 >= 20
    const event = makeDropEvent({ nodeType: 'test-node', clientX: 50, clientY: 50 })

    onDrop(event)

    expect(mockAddNode).toHaveBeenCalledTimes(1)
    expect(mockRemoveEdge).not.toHaveBeenCalled()
    expect(mockAddEdge).not.toHaveBeenCalled()
  })

  it('多条 edge 时命中距离最近的一条', () => {
    mockEdges.value = [
      makeGraphEdge({
        id: 'edge-far',
        source: 'node-a',
        target: 'node-b',
        sourceX: 0,
        sourceY: 0,
        targetX: 100,
        targetY: 0,
      }),
      makeGraphEdge({
        id: 'edge-near',
        source: 'node-c',
        target: 'node-d',
        sourceX: 40,
        sourceY: 0,
        targetX: 60,
        targetY: 0,
      }),
    ]

    const { onDrop } = useDragAndDrop()
    // 点 (50, 5) 到 edge-far 距离 5，到 edge-near 距离 5（并列）
    // 由于 edge-far 先遍历且 dist < minDistance，会被选中
    const event = makeDropEvent({ nodeType: 'test-node', clientX: 50, clientY: 5 })

    onDrop(event)

    expect(mockRemoveEdge).toHaveBeenCalledTimes(1)
    // 第一个满足条件的 edge 被移除
    expect(mockRemoveEdge).toHaveBeenCalledWith('edge-far')
  })
})

describe('useDragAndDrop — onDragOver', () => {
  it('设置 dropEffect 为 move', () => {
    const { onDragOver } = useDragAndDrop()
    const dt = { dropEffect: '' } as unknown as DataTransfer
    const event = {
      preventDefault: vi.fn(),
      dataTransfer: dt,
    } as unknown as DragEvent

    onDragOver(event)

    expect(event.preventDefault).toHaveBeenCalled()
    expect(dt.dropEffect).toBe('move')
  })
})

describe('useDragAndDrop — recordRecentNode 副作用', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEdges.value = []
    localStorageMock.clear()
    dispatchEventSpy.mockClear()
  })

  it('onDrop 后 localStorage 记录最近使用节点', () => {
    const { onDrop } = useDragAndDrop()
    const event = makeDropEvent({ nodeType: 'my-node', clientX: 10, clientY: 10 })

    onDrop(event)

    const stored = localStorageMock.getItem('friday-recent-nodes')
    expect(stored).not.toBeNull()
    const parsed = JSON.parse(stored!)
    expect(parsed).toEqual(['my-node'])
  })

  it('onDrop 后触发 friday:recent-nodes-changed 自定义事件', () => {
    const { onDrop } = useDragAndDrop()
    const event = makeDropEvent({ nodeType: 'my-node', clientX: 10, clientY: 10 })

    onDrop(event)

    expect(dispatchEventSpy).toHaveBeenCalled()
    const dispatched = dispatchEventSpy.mock.calls.find(
      c => c[0] instanceof CustomEvent && c[0].type === 'friday:recent-nodes-changed',
    )
    expect(dispatched).toBeDefined()
  })

  it('localStorage 最多保留 MAX_RECENT 个条目（10 个）', () => {
    const { onDrop } = useDragAndDrop()
    // 先预填充 10 个不同节点
    const existing = Array.from({ length: 10 }, (_, i) => `node-${i}`)
    localStorageMock.setItem('friday-recent-nodes', JSON.stringify(existing))

    const event = makeDropEvent({ nodeType: 'new-node', clientX: 10, clientY: 10 })
    onDrop(event)

    const stored = JSON.parse(localStorageMock.getItem('friday-recent-nodes')!)
    expect(stored).toHaveLength(10)
    expect(stored[0]).toBe('new-node')
    expect(stored).not.toContain('node-9')
  })
})

describe('getRecentNodes', () => {
  beforeEach(() => {
    localStorageMock.clear()
  })

  it('localStorage 无数据时返回空数组', () => {
    expect(getRecentNodes()).toEqual([])
  })

  it('localStorage 有合法数据时返回解析后的数组', () => {
    localStorageMock.setItem('friday-recent-nodes', JSON.stringify(['a', 'b']))
    expect(getRecentNodes()).toEqual(['a', 'b'])
  })

  it('localStorage 数据非法时返回空数组', () => {
    localStorageMock.setItem('friday-recent-nodes', 'not-json')
    expect(getRecentNodes()).toEqual([])
  })
})
