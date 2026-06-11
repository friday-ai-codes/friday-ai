import type { GalaxyEdge, GalaxyEdgeType, GalaxyMeta, GalaxyNode, GalaxyNodeType, GetGalaxyParams } from '~/api/galaxy'
import { computed, ref } from 'vue'
import { getGalaxyGraph } from '~/api/galaxy'

const ALL_NODE_TYPES: GalaxyNodeType[] = ['chunk_registry', 'symbol', 'endpoint', 'api_wrapper', 'api_call_site']
const ALL_EDGE_TYPES: GalaxyEdgeType[] = ['CALL', 'IMPORT', 'SAME_FILE', 'TEST_OF', 'CO_CHANGED', 'SEMANTIC', 'API_CALLS', 'IMPLEMENTS']

export function useGalaxyGraph() {
  const nodes = ref<GalaxyNode[]>([])
  const edges = ref<GalaxyEdge[]>([])
  const meta = ref<GalaxyMeta | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 采样参数
  const maxNodes = ref(500)

  // 节点/边类型过滤（默认全选）。
  // 过滤通过 Sigma reducer 的 hidden 实现 —— 切换不重建图、不丢布局。
  const activeNodeTypes = ref<Set<GalaxyNodeType>>(new Set(ALL_NODE_TYPES))
  const activeEdgeTypes = ref<Set<GalaxyEdgeType>>(new Set(ALL_EDGE_TYPES))

  // FPS 监控（仅展示）
  const fps = ref(60)

  // 过滤后的视图（供搜索面板 / 空状态判断使用；渲染层走 reducer hidden）
  const filteredNodes = computed(() =>
    nodes.value.filter(n => activeNodeTypes.value.has(n.type)),
  )

  const filteredEdges = computed(() => {
    const nodeIds = new Set(filteredNodes.value.map(n => n.id))
    return edges.value.filter(
      e =>
        activeEdgeTypes.value.has(e.edge_type)
        && nodeIds.has(e.source)
        && nodeIds.has(e.target),
    )
  })

  async function fetchGraph(repoIds: string[]) {
    loading.value = true
    error.value = null

    const params: GetGalaxyParams = {
      repoIds,
      maxNodes: maxNodes.value,
    }

    try {
      const result = await getGalaxyGraph(params)
      nodes.value = result.nodes
      edges.value = result.edges
      meta.value = result.meta
    }
    catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载 Galaxy 图谱失败'
    }
    finally {
      loading.value = false
    }
  }

  function onFpsUpdate(currentFps: number) {
    fps.value = currentFps
  }

  function toggleNodeType(type: GalaxyNodeType) {
    const next = new Set(activeNodeTypes.value)
    if (next.has(type))
      next.delete(type)
    else
      next.add(type)
    activeNodeTypes.value = next
  }

  function toggleEdgeType(type: GalaxyEdgeType) {
    const next = new Set(activeEdgeTypes.value)
    if (next.has(type))
      next.delete(type)
    else
      next.add(type)
    activeEdgeTypes.value = next
  }

  function setAllNodeTypes(active: boolean) {
    activeNodeTypes.value = active ? new Set(ALL_NODE_TYPES) : new Set()
  }

  function setAllEdgeTypes(active: boolean) {
    activeEdgeTypes.value = active ? new Set(ALL_EDGE_TYPES) : new Set()
  }

  return {
    nodes,
    edges,
    meta,
    loading,
    error,
    maxNodes,
    activeNodeTypes,
    activeEdgeTypes,
    fps,
    filteredNodes,
    filteredEdges,
    fetchGraph,
    onFpsUpdate,
    toggleNodeType,
    toggleEdgeType,
    setAllNodeTypes,
    setAllEdgeTypes,
  }
}
