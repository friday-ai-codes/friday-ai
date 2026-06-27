/**
 * useWorkflowsStore 父子附着单元测试（SLOT-04）。
 *
 * 覆盖：
 * - attachChild 写入 metadata.parentNodeId 并设相对坐标。
 * - detachChild 清除 metadata.parentNodeId（delete 键，不残留）并恢复绝对坐标。
 * - removeNode(父) 级联删除全部附着子节点 + 两者相关边。
 * - removeNode(普通节点) 行为零回归（只删自身 + 连边，不波及他人）。
 * - metadata.parentNodeId 经 toBackendNodes → toStoreNodes 往返保留（save/reload 不丢）。
 * - getChildNodes 取某父的附着子集。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('~/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number
    body: unknown
    constructor(status = 0, body: unknown = null) {
      super('ApiError')
      this.status = status
      this.body = body
    }
  },
}))

const client = (await import('~/api/client')).default as unknown as {
  put: ReturnType<typeof vi.fn>
}
const { useWorkflowsStore } = await import('../useWorkflowsStore')

type Store = ReturnType<typeof useWorkflowsStore>

function makeNode(id: string, overrides: Record<string, any> = {}) {
  return {
    id,
    shortId: id.slice(0, 3),
    nodeType: 'ai_prompt',
    name: id,
    description: '',
    position: { x: 0, y: 0 },
    config: {},
    onError: 'abort' as const,
    retryTimes: 0,
    retryDelay: 5,
    nodeTimeoutSeconds: null,
    fallbackValues: null,
    runCondition: null,
    metadata: {} as Record<string, unknown>,
    ...overrides,
  }
}

let store: Store

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkflowsStore()
  vi.clearAllMocks()
})

describe('useWorkflowsStore - attachChild / detachChild', () => {
  it('attachChild 写入 metadata.parentNodeId 并设相对坐标', () => {
    store.nodes = [makeNode('parent'), makeNode('child')]

    store.attachChild('child', 'parent', { x: 20, y: 30 })

    const child = store.getNodeById('child')!
    expect(child.metadata.parentNodeId).toBe('parent')
    expect(child.position).toEqual({ x: 20, y: 30 })
  })

  it('detachChild 清除 metadata.parentNodeId（不残留键）并恢复绝对坐标', () => {
    store.nodes = [
      makeNode('parent'),
      makeNode('child', { metadata: { parentNodeId: 'parent', foo: 'bar' }, position: { x: 20, y: 30 } }),
    ]

    store.detachChild('child', { x: 400, y: 500 })

    const child = store.getNodeById('child')!
    expect('parentNodeId' in child.metadata).toBe(false)
    // 保留其它 metadata 字段
    expect(child.metadata.foo).toBe('bar')
    expect(child.position).toEqual({ x: 400, y: 500 })
  })

  it('attach 入历史一次（单步可撤销，含 fetchWorkflow 初始 seed）', () => {
    // 模拟 fetchWorkflow seed 初始快照（historyIndex=0），再 attach 应再入一帧 → canUndo
    store.nodes = [makeNode('parent'), makeNode('child')]
    store.saveToHistory()
    store.attachChild('child', 'parent', { x: 1, y: 2 })
    expect(store.hasUnsavedChanges).toBe(true)
    expect(store.canUndo).toBe(true)
  })

  it('getChildNodes 取某父的全部附着子节点', () => {
    store.nodes = [
      makeNode('parent'),
      makeNode('c1', { metadata: { parentNodeId: 'parent' } }),
      makeNode('c2', { metadata: { parentNodeId: 'parent' } }),
      makeNode('other'),
    ]
    const children = store.getChildNodes('parent')
    expect(children.map(n => n.id).sort()).toEqual(['c1', 'c2'])
  })
})

describe('useWorkflowsStore - removeNode 级联删除', () => {
  it('删父方案节点时级联删除其附着子节点 + 两者相关边', () => {
    store.nodes = [
      makeNode('parent'),
      makeNode('child', { metadata: { parentNodeId: 'parent' } }),
      makeNode('keep'),
    ]
    store.edges = [
      { id: 'e1', source: 'parent', sourcePort: 'default', target: 'keep', targetPort: 'default', condition: null },
      { id: 'e2', source: 'keep', sourcePort: 'default', target: 'child', targetPort: 'default', condition: null },
      { id: 'e3', source: 'keep', sourcePort: 'default', target: 'keep', targetPort: 'default', condition: null },
    ]

    store.removeNode('parent')

    expect(store.nodes.map(n => n.id)).toEqual(['keep'])
    // e1（连父）、e2（连子）都被移除，e3 保留
    expect(store.edges.map(e => e.id)).toEqual(['e3'])
  })

  it('删普通节点（无子）行为零回归：只删自身 + 连边', () => {
    store.nodes = [makeNode('a'), makeNode('b'), makeNode('c')]
    store.edges = [
      { id: 'e1', source: 'a', sourcePort: 'default', target: 'b', targetPort: 'default', condition: null },
      { id: 'e2', source: 'b', sourcePort: 'default', target: 'c', targetPort: 'default', condition: null },
    ]

    store.removeNode('b')

    expect(store.nodes.map(n => n.id)).toEqual(['a', 'c'])
    // b 的两条连边都删，无残留
    expect(store.edges).toEqual([])
  })
})

describe('useWorkflowsStore - metadata.parentNodeId 持久化往返', () => {
  it('attach 后经 saveWorkflow（toBackendNodes）上送 metadata.parentNodeId，reload（toStoreNodes）后保留', async () => {
    store.currentWorkflow = { id: 'wf1', nodes: [], edges: [] } as any
    store.nodes = [makeNode('parent'), makeNode('child')]
    store.attachChild('child', 'parent', { x: 10, y: 20 })

    // mock 后端 bulk-update：捕获上送 payload，并把节点以后端 snake_case 形态回显
    client.put.mockImplementation(async (_url: string, payload: any) => {
      return {
        id: 'wf1',
        nodes: payload.nodes.map((n: any) => ({
          id: n.id,
          short_id: n.short_id,
          node_type: n.node_type,
          name: n.name,
          description: n.description,
          position_x: n.position_x,
          position_y: n.position_y,
          config: n.config,
          on_error: n.on_error,
          retry_times: n.retry_times,
          retry_delay: n.retry_delay,
          node_timeout_seconds: n.node_timeout_seconds,
          fallback_values: n.fallback_values,
          run_condition: n.run_condition,
          metadata: n.metadata,
        })),
        edges: [],
      }
    })

    await store.saveWorkflow()

    // 1) 上送 payload 中子节点 metadata.parentNodeId 存在（toBackendNodes 透传）
    const sent = client.put.mock.calls[0][1]
    const sentChild = sent.nodes.find((n: any) => n.id === 'child')
    expect(sentChild.metadata.parentNodeId).toBe('parent')

    // 2) reload 后 store 子节点仍带 parentNodeId（toStoreNodes 透传）
    const reloadedChild = store.getNodeById('child')!
    expect(reloadedChild.metadata.parentNodeId).toBe('parent')
  })
})
