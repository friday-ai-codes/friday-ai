import type { GraphEdge, GraphNode } from '@vue-flow/core'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

// ---------------------------------------------------------------------------
// 被测模块（在 mock 之后导入）
// ---------------------------------------------------------------------------
import { getRecentNodes, useDragAndDrop } from '../useDragAndDrop'

// ---------------------------------------------------------------------------
// Mock 设置
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
// Fixture 工厂
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
// 测试套件
// ---------------------------------------------------------------------------

describe('useDragAndDrop — onDrop', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockEdges.value = []
    mockScreenToFlowCoordinate.mockImplementation(({ x, y }: { x: number, y: number }) => ({ x, y }))
    localStorageMock.clear()
    dispatchEventSpy.mockClear()
  })

  it('无 edge 时直接添加节点，调用 store.addNode，不调用 removeEdge/addEdge', () => {
    const { onDrop } = useDragAndDrop()
    const event = makeDropEvent({ nodeType: 'test-node', clientX: 50, clientY: 50 })

    onDrop(event)

    expect(mockAddNode).toHaveBeenCalledTimes(1)
    expect(mockRemoveEdge).not.toHaveBeenCalled()
    expect(mockAddEdge).not.toHaveBeenCalled()
  })

  it('有 edge 存在时 drop 也只 addNode，不再命中连线插入（不 removeEdge/addEdge）', () => {
    // 边中插入已改由边中点 "+" 承担，拖放始终只新增节点。
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
    // 即便落点正好在连线上（点 (50,10) 距线段 (0,0)-(100,0) 仅 10px），也不再断线插入
    const event = makeDropEvent({ nodeType: 'test-node', clientX: 50, clientY: 10 })

    onDrop(event)

    expect(mockAddNode).toHaveBeenCalledTimes(1)
    expect(mockRemoveEdge).not.toHaveBeenCalled()
    expect(mockAddEdge).not.toHaveBeenCalled()
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
