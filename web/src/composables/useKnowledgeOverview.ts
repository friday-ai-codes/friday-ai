import type { CollectionHealthResponse, GraphRagStatusResponse, IndexStatusResponse } from '~/api/repositories'
import type { Repository } from '~/types'
import { getCodegraphStats } from '~/api/codegraph'
import { IndexStatus, repositoriesApi } from '~/api/repositories'

export type FreshnessState = 'fresh' | 'stale' | 'not_indexed' | 'unknown'

export function computeFreshness(r: Repository): FreshnessState {
  if (!r.last_indexed_commit_sha)
    return 'not_indexed'
  if (!r.remote_head_sha || !r.remote_head_checked_at)
    return 'unknown'
  return r.remote_head_sha === r.last_indexed_commit_sha ? 'fresh' : 'stale'
}

export function useKnowledgeOverview(
  repositoryId: Ref<string>,
  branch?: Ref<string | null | undefined>,
) {
  const loading = ref(true)
  const checking = ref(false)
  const errorMessage = ref<string | null>(null)

  const repo = ref<Repository | null>(null)
  const indexStatus = ref<IndexStatusResponse | null>(null)
  const health = ref<CollectionHealthResponse | null>(null)
  const graphRagStatus = ref<GraphRagStatusResponse | null>(null)
  const structuredGraphCounts = ref<{
    symbols: number
    imports: number
    calls: number
    endpoints: number
  } | null>(null)

  const freshnessState = ref<FreshnessState>('unknown')
  const latestRemoteHeadSha = ref('')

  async function loadRepo() {
    repo.value = await repositoriesApi.get(repositoryId.value)
    freshnessState.value = computeFreshness(repo.value)
    latestRemoteHeadSha.value = repo.value.remote_head_sha || ''
  }

  async function loadIndexStatus() {
    try {
      indexStatus.value = await repositoriesApi.getIndexStatus(repositoryId.value)
    }
    catch {
      indexStatus.value = null
    }
  }

  async function loadHealth() {
    try {
      health.value = await repositoriesApi.getCollectionHealth(repositoryId.value)
    }
    catch {
      health.value = null
    }
  }

  async function loadGraphRagStatus() {
    try {
      // 直接读 ChunkEdge 表真实计数（不再依赖 IndexHistory.edge_count 快照，
      // 修复时序漏写导致的"0 语义边"误显示）
      graphRagStatus.value = await repositoriesApi.getGraphRagStatus(repositoryId.value, branch?.value)
    }
    catch {
      graphRagStatus.value = null
    }
  }

  async function loadStructuredGraphCounts() {
    try {
      // 读 codegraph 各表累计计数（getCodegraphStats），而非最近一次 GraphBuildHistory
      // 的 per-run delta —— 后者在增量构建（只处理变更文件）后会让"关系数"暴跌/误显示。
      const stats = await getCodegraphStats(repositoryId.value)
      structuredGraphCounts.value = stats.total > 0
        ? {
            symbols: stats.symbols,
            imports: stats.imports,
            calls: stats.calls,
            endpoints: stats.endpoints,
          }
        : null
    }
    catch {
      structuredGraphCounts.value = null
    }
  }

  async function loadAll() {
    loading.value = true
    errorMessage.value = null
    try {
      await Promise.all([
        loadRepo(),
        loadIndexStatus(),
        loadHealth(),
        loadGraphRagStatus(),
        loadStructuredGraphCounts(),
      ])
    }
    catch {
      errorMessage.value = '加载知识库概览失败'
    }
    finally {
      loading.value = false
    }
  }

  async function refreshFreshness() {
    checking.value = true
    errorMessage.value = null
    try {
      const res = await repositoriesApi.refreshRemoteHead(repositoryId.value)
      latestRemoteHeadSha.value = res.remote_head_sha
      await loadRepo()
      await Promise.all([loadHealth(), loadGraphRagStatus()])
    }
    catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '未知错误'
      errorMessage.value = `检查失败：${msg}`
    }
    finally {
      checking.value = false
    }
  }

  const structuredGraphTotal = computed(() => {
    if (!structuredGraphCounts.value)
      return 0
    const c = structuredGraphCounts.value
    return c.symbols + c.imports + c.calls + c.endpoints
  })

  const indexBusy = computed(() => indexStatus.value?.index_status === IndexStatus.INDEXING)
  const graphBusy = computed(() => repo.value?.graph_build_status === 'running')

  watch(repositoryId, () => {
    loadAll()
  })

  // 切分支只重拉 branch-aware 的 graphrag-status，避免整页 loading 抖动；
  // repo/health/structuredCounts 维持现状不随分支变（Pitfall D）。
  watch(() => branch?.value, () => {
    loadGraphRagStatus()
  })

  return {
    loading,
    checking,
    errorMessage,
    repo,
    indexStatus,
    health,
    graphRagStatus,
    structuredGraphCounts,
    structuredGraphTotal,
    freshnessState,
    latestRemoteHeadSha,
    indexBusy,
    graphBusy,
    loadAll,
    refreshFreshness,
    loadStructuredGraphCounts,
    loadGraphRagStatus,
    loadIndexStatus,
    loadRepo,
  }
}
