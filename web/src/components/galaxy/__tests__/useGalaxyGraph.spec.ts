import type { GalaxyEdge, GalaxyNode, GalaxyResponse } from '~/api/galaxy'
/**
 * — useGalaxyGraph composable 单测
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGalaxyGraph } from '~/composables/useGalaxyGraph'

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
    id: 'symbol:uuid-2',
    type: 'symbol',
    label: 'MyClass',
    repository_id: 'repo-1',
    file_path: 'src/foo.py',
    line_start: 1,
    line_end: 20,
    metadata: {},
    degree: 3,
  },
  {
    id: 'endpoint:uuid-3',
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
    target: 'symbol:uuid-2',
    edge_type: 'CALL',
    weight: 0.9,
    repository_id: 'repo-1',
    target_repository_id: null,
    metadata: {},
  },
  {
    id: 'edge-2',
    source: 'symbol:uuid-2',
    target: 'endpoint:uuid-3',
    edge_type: 'API_CALLS',
    weight: 0.8,
    repository_id: 'repo-1',
    target_repository_id: 'repo-2',
    metadata: {},
  },
  {
    id: 'edge-3',
    source: 'chunk_registry:uuid-1',
    target: 'endpoint:uuid-3',
    edge_type: 'IMPORT',
    weight: 0.5,
    repository_id: 'repo-1',
    target_repository_id: null,
    metadata: {},
  },
]

const mockResponse: GalaxyResponse = {
  nodes: mockNodes,
  edges: mockEdges,
  meta: {
    total_nodes: 3,
    total_edges: 3,
    sampled: false,
    per_repo_hint: false,
    max_nodes: 500,
  },
}

vi.mock('~/api/galaxy', () => ({
  getGalaxyGraph: vi.fn(),
}))

describe('useGalaxyGraph', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('fetchGraph 成功 — nodes/edges/meta 正确更新', async () => {
    const { getGalaxyGraph } = await import('~/api/galaxy')
    vi.mocked(getGalaxyGraph).mockResolvedValueOnce(mockResponse)

    const { fetchGraph, nodes, edges, meta, loading, error } = useGalaxyGraph()
    expect(loading.value).toBe(false)

    const fetchPromise = fetchGraph(['repo-1'])
    expect(loading.value).toBe(true)

    await fetchPromise
    expect(loading.value).toBe(false)
    expect(error.value).toBeNull()
    expect(nodes.value).toHaveLength(3)
    expect(edges.value).toHaveLength(3)
    expect(meta.value).not.toBeNull()
    expect(meta.value?.total_nodes).toBe(3)
    expect(meta.value?.sampled).toBe(false)
  })

  it('fetchGraph 失败 — error state 更新，loading 恢复 false', async () => {
    const { getGalaxyGraph } = await import('~/api/galaxy')
    vi.mocked(getGalaxyGraph).mockRejectedValueOnce(new Error('Network Error'))

    const { fetchGraph, error, loading } = useGalaxyGraph()
    await fetchGraph(['repo-1'])

    expect(loading.value).toBe(false)
    expect(error.value).toBe('Network Error')
  })

  it('filteredEdges — toggleEdgeType 过滤正确', async () => {
    const { getGalaxyGraph } = await import('~/api/galaxy')
    vi.mocked(getGalaxyGraph).mockResolvedValueOnce(mockResponse)

    const { fetchGraph, filteredEdges, toggleEdgeType } = useGalaxyGraph()
    await fetchGraph(['repo-1'])

    // 初始全选：3 条边全部返回
    expect(filteredEdges.value).toHaveLength(3)

    // 移除 CALL 类型
    toggleEdgeType('CALL')
    expect(filteredEdges.value).toHaveLength(2)

    // 移除 API_CALLS 类型
    toggleEdgeType('API_CALLS')
    expect(filteredEdges.value).toHaveLength(1)
    expect(filteredEdges.value[0].edge_type).toBe('IMPORT')

    // 再次 toggle 恢复
    toggleEdgeType('CALL')
    expect(filteredEdges.value).toHaveLength(2)
  })

  it('filteredNodes — toggleNodeType 过滤正确', async () => {
    const { getGalaxyGraph } = await import('~/api/galaxy')
    vi.mocked(getGalaxyGraph).mockResolvedValueOnce(mockResponse)

    const { fetchGraph, filteredNodes, toggleNodeType } = useGalaxyGraph()
    await fetchGraph(['repo-1'])

    expect(filteredNodes.value).toHaveLength(3)

    // 移除 endpoint 类型
    toggleNodeType('endpoint')
    expect(filteredNodes.value).toHaveLength(2)
    expect(filteredNodes.value.every(n => n.type !== 'endpoint')).toBe(true)
  })

  it('toggle 操作生成新 Set 实例（保证 props 浅层 watch 能感知变化）', () => {
    const { activeNodeTypes, toggleNodeType, setAllNodeTypes } = useGalaxyGraph()

    const before = activeNodeTypes.value
    toggleNodeType('symbol')
    expect(activeNodeTypes.value).not.toBe(before)

    const mid = activeNodeTypes.value
    setAllNodeTypes(false)
    expect(activeNodeTypes.value).not.toBe(mid)
    expect(activeNodeTypes.value.size).toBe(0)

    setAllNodeTypes(true)
    expect(activeNodeTypes.value.size).toBe(5)
  })

  it('onFpsUpdate — 更新 fps 值', () => {
    const { onFpsUpdate, fps } = useGalaxyGraph()

    expect(fps.value).toBe(60)
    onFpsUpdate(42)
    expect(fps.value).toBe(42)
  })
})
