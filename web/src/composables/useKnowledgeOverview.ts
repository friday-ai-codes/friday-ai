import type { GraphBuildHistoryItem } from '~/api/codegraph'
import type { CollectionHealthResponse, GraphRagStatusResponse, IndexStatusResponse } from '~/api/repositories'
import type { Repository } from '~/types'
import { listGraphHistory } from '~/api/codegraph'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
export type FreshnessState = 'fresh' | 'stale' | 'not_indexed' | 'unknown'
export function computeFreshness(r: Repository): FreshnessState {
 if (!r.last_indexed_commit_sha)
 return 'not_indexed'
 if (!r.remote_head_sha || !r.remote_head_checked_at)
 return 'unknown'
 return r.remote_head_sha === r.last_indexed_commit_sha ? 'fresh': 'stale'
}
export function useKnowledgeOverview(repositoryId: Ref<string>) {
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
 async function loadRepo {
 repo.value = await repositoriesApi.get(repositoryId.value)
 freshnessState.value = computeFreshness(repo.value)
 latestRemoteHeadSha.value = repo.value.remote_head_sha || ''
 }
 async function loadIndexStatus {
 try {
 indexStatus.value = await repositoriesApi.getIndexStatus(repositoryId.value)
 }
 catch {
 indexStatus.value = null
 }
 }
 async function loadHealth {
 try {
 health.value = await repositoriesApi.getCollectionHealth(repositoryId.value)
 }
 catch {
 health.value = null
 }
 }
 async function loadGraphRagStatus {
 try {
 // 直接读 ChunkEdge 表真实计数（不再依赖 IndexHistory.edge_count 快照，
 // 修复时序漏写导致的"0 语义边"误显示）
 graphRagStatus.value = await repositoriesApi.getGraphRagStatus(repositoryId.value)
 }
 catch {
 graphRagStatus.value = null
 }
 }
 async function loadStructuredGraphCounts {
 try {
 const res = await listGraphHistory(repositoryId.value, { limit: 1, status: 'completed' })
 const item: GraphBuildHistoryItem | undefined = res.results[0]
 structuredGraphCounts.value = item
 ? {
 symbols: item.symbols_count,
 imports: item.imports_count,
 calls: item.calls_count,
 endpoints: item.endpoints_count,
 }: null
 }
 catch {
 structuredGraphCounts.value = null
 }
 }
 async function loadAll {
 loading.value = true
 errorMessage.value = null
 try {
 await Promise.all([
 loadRepo,
 loadIndexStatus,
 loadHealth,
 loadGraphRagStatus,
 loadStructuredGraphCounts,
 ])
 }
 catch {
 errorMessage.value = '加载知识库概览失败'
 }
 finally {
 loading.value = false
 }
 }
 async function refreshFreshness {
 checking.value = true
 errorMessage.value = null
 try {
 const res = await repositoriesApi.refreshRemoteHead(repositoryId.value)
 latestRemoteHeadSha.value = res.remote_head_sha
 await loadRepo
 await Promise.all([loadHealth, loadGraphRagStatus])
 }
 catch (e: unknown) {
 const msg = e instanceof Error ? e.message: '未知错误'
 errorMessage.value = `检查失败：${msg}`
 }
 finally {
 checking.value = false
 }
 }
 const structuredGraphTotal = computed( => {
 if (!structuredGraphCounts.value)
 return 0
 const c = structuredGraphCounts.value
 return c.symbols + c.imports + c.calls + c.endpoints
 })
 const indexBusy = computed( => indexStatus.value?.index_status === IndexStatus.INDEXING)
 const graphBusy = computed( => repo.value?.graph_build_status === 'running')
 watch(repositoryId, => {
 loadAll
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
