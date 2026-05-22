<script setup lang="ts">
/**
 * RepositoryGraphCard — 代码图谱构建卡片（Phase GRAPH- + GRAPH-）
 *
 * 视觉 1:1 对齐 RepositoryIndexCard.vue：`.card` 容器 + `px-5 py-3.5 border-b`
 * Header + `` content + `flex flex-wrap gap-2` 按钮组（DESIGN.md / work item §3）。
 *
 * 5 态分支：
 * - idle → 空态 + 「立即构建」
 * - running → 进度区（current_file + N/M + stage + percent + 进度条）+ 「停止构建」
 * - completed → 4 count 统计（symbols/imports/calls/endpoints）+ 最近构建时间 + 「重新构建」+「只清图谱」
 * - failed → error_message 卡片 + 「重新构建」+「只清图谱」
 * - cancelled → 已停止提示 + 「重新构建」+「只清图谱」
 *
 * SSE 消费：调用 connectGraphProgressStream，progress 帧实时覆盖快照字段；
 * done 帧到达后拉 GET /repositories/<id>/ 拿权威终态，若 completed 再独立
 * 拉 GET /codegraph/history/?limit=1&status=completed 拿 4 count（work item §3.6）。
 * SSE onError 时降级为 3s polling /repositories/<id>/ 直到非 running 终态。
 */
import type { GraphBuildHistoryItem, GraphBuildStatus, GraphPayload } from '~/api/codegraph'
import type { Repository } from '~/types'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
 cancelGraphBuild,
 deleteGraph,
 listGraphHistory,
 rebuildGraph,
} from '~/api/codegraph'
import { repositoriesApi } from '~/api/repositories'
import StatusBadge from '~/components/common/StatusBadge.vue'
import GraphAutoBuildToggle from '~/components/repository/GraphAutoBuildToggle.vue'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
 AlertDialogTrigger,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { connectGraphProgressStream } from '~/composables/useGraphBuildStream'
import { useToast } from '~/composables/useToast'
import { formatRelativeTime } from '~/lib/relativeTime'
const props = withDefaults(defineProps<{
 repositoryId: string
 /** 嵌入知识库 Hub 时隐藏外层 card 壳 */
 embedded?: boolean
}>, {
 embedded: false,
})
const loading = ref(true)
const repository = ref<Repository | null>(null)
// SSE 实时进度帧（覆盖 Repository 快照同名字段）
const liveGraph = ref<GraphPayload | null>(null)
// completed 终态独立拉 4 count（work item §3.6 数据策略）
const lastCompletedCounts = ref<{
 symbols: number
 imports: number
 calls: number
 endpoints: number
} | null>(null)
const rebuilding = ref(false)
const cancelling = ref(false)
const deleting = ref(false)
const showDeleteDialog = ref(false)
let streamController: AbortController | null = null
let pollInterval: ReturnType<typeof setInterval> | null = null
const { handleError } = useErrorHandler
const { success } = useToast
// ===== 派生状态 =====
const graphStatus = computed<GraphBuildStatus>( => {
 return liveGraph.value?.status ?? repository.value?.graph_build_status ?? 'idle'
})
const stage = computed( => liveGraph.value?.stage ?? repository.value?.graph_stage ?? '准备中...')
const currentFile = computed( => liveGraph.value?.current_file ?? repository.value?.current_graph_file ?? '')
const filesProcessed = computed( => liveGraph.value?.files_processed ?? repository.value?.graph_files_processed ?? 0)
const filesTotal = computed( => liveGraph.value?.files_total ?? repository.value?.graph_files_total ?? 0)
const percent = computed( => {
 if (liveGraph.value?.percent !== undefined && liveGraph.value.percent !== null)
 return liveGraph.value.percent
 if (filesTotal.value > 0)
 return Math.min(100, Math.round((filesProcessed.value / filesTotal.value) * 100))
 return 0
})
const errorMessage = computed( => liveGraph.value?.error_message ?? '')
const hasCurrentFile = computed( => currentFile.value.length > 0)
const hasFilesCounter = computed( => filesTotal.value > 0)
const filesPercent = computed( => {
 if (filesTotal.value <= 0)
 return null
 return Math.min(100, Math.round((filesProcessed.value / filesTotal.value) * 100))
})
const indexBusy = computed( => repository.value?.index_status === 'indexing')
// ===== 数据加载 =====
async function loadRepository {
 try {
 repository.value = await repositoriesApi.get(props.repositoryId)
 }
 catch (err) {
 handleError(err, '加载仓库快照')
 }
 finally {
 loading.value = false
 }
}
async function loadLatestCompletedCounts {
 try {
 const res = await listGraphHistory(props.repositoryId, { limit: 1, status: 'completed' })
 const item: GraphBuildHistoryItem | undefined = res.results[0]
 if (item) {
 lastCompletedCounts.value = {
 symbols: item.symbols_count,
 imports: item.imports_count,
 calls: item.calls_count,
 endpoints: item.endpoints_count,
 }
 }
 else {
 lastCompletedCounts.value = null
 }
 }
 catch {
 lastCompletedCounts.value = null
 }
}
// ===== SSE / polling =====
function startStream {
 if (streamController)
 return
 streamController = connectGraphProgressStream(props.repositoryId, {
 onEvent: (event) => {
 if (event.type === 'progress') {
 liveGraph.value = event.graph
 }
 else if (event.type === 'done') {
 stopAllWatchers
 loadRepository.then( => {
 const finalStatus = repository.value?.graph_build_status
 if (finalStatus === 'completed') {
 loadLatestCompletedCounts
 success('图谱构建完成')
 }
 else if (finalStatus === 'cancelled') {
 success('图谱构建已停止')
 }
 // failed 由 error_message 卡片承担，避免双 toast
 })
 }
 },
 onError: => {
 stopStream
 startPollingFallback
 },
 })
}
function stopStream {
 streamController?.abort
 streamController = null
}
function startPollingFallback {
 if (pollInterval)
 return
 pollInterval = setInterval(async => {
 await loadRepository
 if (repository.value?.graph_build_status !== 'running') {
 const finalStatus = repository.value?.graph_build_status
 stopAllWatchers
 if (finalStatus === 'completed') {
 await loadLatestCompletedCounts
 }
 }
 }, 3000)
}
function stopPolling {
 if (pollInterval) {
 clearInterval(pollInterval)
 pollInterval = null
 }
}
function stopAllWatchers {
 stopStream
 stopPolling
}
// ===== 按钮交互 =====
async function triggerRebuild {
 if (rebuilding.value || indexBusy.value)
 return
 rebuilding.value = true
 try {
 await rebuildGraph(props.repositoryId)
 success('已开始构建图谱')
 liveGraph.value = null
 await loadRepository
 startStream
 }
 catch (err) {
 handleError(err, '触发图谱构建')
 }
 finally {
 rebuilding.value = false
 }
}
async function triggerCancel {
 if (cancelling.value)
 return
 cancelling.value = true
 try {
 await cancelGraphBuild(props.repositoryId)
 // 不立即关 SSE，等后端推完终态帧（work item §4.2）
 }
 catch (err) {
 handleError(err, '停止图谱构建')
 }
 finally {
 cancelling.value = false
 }
}
async function triggerDelete {
 if (deleting.value)
 return
 deleting.value = true
 try {
 await deleteGraph(props.repositoryId)
 success('已清空图谱数据')
 lastCompletedCounts.value = null
 liveGraph.value = null
 await loadRepository
 }
 catch (err) {
 handleError(err, '清空图谱')
 }
 finally {
 deleting.value = false
 showDeleteDialog.value = false
 }
}
// ===== 生命周期 =====
watch( => repository.value?.graph_build_status, (next) => {
 if (next === 'running' && !streamController)
 startStream
})
onMounted(async => {
 await loadRepository
 if (repository.value?.graph_build_status === 'running')
 startStream
 if (repository.value?.graph_build_status === 'completed')
 await loadLatestCompletedCounts
})
onUnmounted( => {
 stopAllWatchers
})
</script>
<template>
 <div:class="embedded ? '': 'card'">
 <!-- ===== Header ===== -->
 <div
 v-if="!embedded"
 class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between"
 >
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--git-graph] text-primary" />
 <h3 class="text-sm font-semibold">
 代码图谱
 </h3>
 <span class="text-xs text-muted-foreground">结构化关系图</span>
 </div>
 <div class="flex items-center gap-3">
 <GraphAutoBuildToggle
 v-if="repository":repository-id="props.repositoryId":initial="repository.auto_build_graph_enabled"
 />
 <StatusBadge type="graph":status="graphStatus" />
 </div>
 </div>
 <!-- embedded 模式：保留自动构建开关与状态 -->
 <div
 v-else
 class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-2"
 >
 <div class="flex items-center gap-2 text-xs text-muted-foreground">
 <span class="icon-[lucide--git-graph] text-primary" />
 结构化关系图构建
 </div>
 <div class="flex items-center gap-2">
 <GraphAutoBuildToggle
 v-if="repository":repository-id="props.repositoryId":initial="repository.auto_build_graph_enabled"
 />
 <StatusBadge type="graph":status="graphStatus" size="sm" />
 </div>
 </div>
 <!-- ===== Content ===== -->
 <div:class="embedded ? '': ''">
 <!-- 加载态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground">加载图谱状态...</span>
 </div>
 <div v-else class="space-y-6">
 <!-- ===== running 态：进度区（work item §3.5） ===== -->
 <div v-if="graphStatus === 'running'" class="space-y-4">
 <div
 v-if="hasCurrentFile || hasFilesCounter"
 class="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 space-y-1.5"
 >
 <div class="flex items-center justify-between gap-3">
 <span class="text-[11px] uppercase tracking-wider text-muted-foreground">
 当前文件
 </span>
 <span
 v-if="hasFilesCounter"
 class="font-mono tabular-nums text-xs text-primary"
 >
 {{ filesProcessed }} / {{ filesTotal }}
 <span v-if="filesPercent !== null" class="text-muted-foreground ml-1">
 ({{ filesPercent }}%)
 </span>
 </span>
 </div>
 <p
 v-if="hasCurrentFile"
 class="font-mono text-sm text-foreground truncate":title="currentFile"
 >
 {{ currentFile }}
 </p>
 <p v-else class="text-sm text-muted-foreground">
 准备中…
 </p>
 </div>
 <div class="space-y-1.5">
 <div class="flex items-center justify-between text-sm">
 <span class="text-muted-foreground inline-flex items-center gap-1.5">
 <span class="icon-[lucide--loader-circle] animate-spin text-primary" />
 {{ stage }}
 </span>
 <span class="font-medium text-primary tabular-nums">{{ percent }}%</span>
 </div>
 <div class=" bg-muted rounded-full overflow-hidden">
 <div
 class="h-full bg-primary transition-all duration-500"
 role="progressbar":aria-valuenow="percent"
 aria-valuemin="0"
 aria-valuemax="100":style="{ width: `${percent}%` }"
 />
 </div>
 </div>
 </div>
 <!-- ===== completed 态：4 count + 最近构建时间（work item §3.6 / §3.7） ===== -->
 <div v-else-if="graphStatus === 'completed'" class="space-y-4">
 <div class="grid grid-cols-4 gap-3">
 <div class="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5">
 <p class="text-[11px] text-muted-foreground mb-0.5 flex items-center gap-1">
 <span class="icon-[lucide--code]" />
 符号
 </p>
 <p class="text-lg font-semibold text-foreground tabular-nums">
 {{ lastCompletedCounts?.symbols ?? '—' }}
 </p>
 </div>
 <div class="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5">
 <p class="text-[11px] text-muted-foreground mb-0.5 flex items-center gap-1">
 <span class="icon-[lucide--arrow-down-to-line]" />
 导入
 </p>
 <p class="text-lg font-semibold text-foreground tabular-nums">
 {{ lastCompletedCounts?.imports ?? '—' }}
 </p>
 </div>
 <div class="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5">
 <p class="text-[11px] text-muted-foreground mb-0.5 flex items-center gap-1">
 <span class="icon-[lucide--phone-call]" />
 调用
 </p>
 <p class="text-lg font-semibold text-foreground tabular-nums">
 {{ lastCompletedCounts?.calls ?? '—' }}
 </p>
 </div>
 <div class="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5">
 <p class="text-[11px] text-muted-foreground mb-0.5 flex items-center gap-1">
 <span class="icon-[lucide--server]" />
 端点
 </p>
 <p class="text-lg font-semibold text-foreground tabular-nums">
 {{ lastCompletedCounts?.endpoints ?? '—' }}
 </p>
 </div>
 </div>
 <p class="text-xs text-muted-foreground">
 最近构建：<span class="text-foreground">{{ formatRelativeTime(repository?.graph_last_built_at) }}</span>
 </p>
 </div>
 <!-- ===== failed 态：错误卡片（work item §3.9） ===== -->
 <div v-else-if="graphStatus === 'failed'" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-destructive/10">
 <span class="icon-[lucide--x-circle] text-2xl text-destructive" />
 </div>
 <div class="min-w-0">
 <p class="font-medium">
 图谱构建失败
 </p>
 <p
 class="text-sm text-muted-foreground truncate":title="errorMessage"
 >
 {{ errorMessage || '未知错误' }}
 </p>
 </div>
 </div>
 <p v-if="repository?.graph_last_built_at" class="text-xs text-muted-foreground">
 最近构建：<span class="text-foreground">{{ formatRelativeTime(repository.graph_last_built_at) }}</span>
 </p>
 </div>
 <!-- ===== cancelled 态：已停止提示 ===== -->
 <div v-else-if="graphStatus === 'cancelled'" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-muted">
 <span class="icon-[lucide--circle-stop] text-2xl text-muted-foreground" />
 </div>
 <div>
 <p class="font-medium">
 图谱构建已停止
 </p>
 <p class="text-sm text-muted-foreground">
 可点&quot;重新构建&quot;再次启动
 </p>
 </div>
 </div>
 <p v-if="repository?.graph_last_built_at" class="text-xs text-muted-foreground">
 最近构建：<span class="text-foreground">{{ formatRelativeTime(repository.graph_last_built_at) }}</span>
 </p>
 </div>
 <!-- ===== idle 态：空态（work item §3.10） ===== -->
 <div v-else class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--git-graph] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground mb-4">
 尚未构建代码图谱
 </p>
 </div>
 <!-- ===== 按钮组（work item §3.8） ===== -->
 <div class="flex flex-wrap gap-2">
 <!-- 查看 Galaxy 图谱（仅 completed 显示） -->
 <Button
 v-if="graphStatus === 'completed'"
 variant="outline"
 as-child
 >
 <router-link:to="{ path: '/codegraph/galaxy', query: { repo_ids: props.repositoryId } }">
 <span class="icon-[lucide--orbit] mr-2" />
 查看 Galaxy 图谱
 </router-link>
 </Button>
 <!-- 立即构建 / 重新构建（idle / completed / failed / cancelled） -->
 <TooltipProvider v-if="['idle', 'completed', 'failed', 'cancelled'].includes(graphStatus)">
 <Tooltip>
 <TooltipTrigger as-child>
 <span class="inline-flex">
 <Button:disabled="rebuilding || indexBusy"
 @click="triggerRebuild"
 >
 <span v-if="rebuilding" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else-if="graphStatus === 'idle'" class="icon-[lucide--play] mr-2" />
 <span v-else class="icon-[lucide--refresh-cw] mr-2" />
 {{ graphStatus === 'idle' ? '立即构建': '重新构建' }}
 </Button>
 </span>
 </TooltipTrigger>
 <TooltipContent v-if="indexBusy">
 <p class="text-xs">
 请等待代码索引完成
 </p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <!-- 停止构建（running） -->
 <Button
 v-if="graphStatus === 'running'"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="cancelling"
 @click="triggerCancel"
 >
 <span v-if="cancelling" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--circle-stop] mr-2" />
 停止构建
 </Button>
 <!-- 只清图谱（completed / failed / cancelled）+ 二次确认 -->
 <AlertDialog v-model:open="showDeleteDialog">
 <AlertDialogTrigger as-child>
 <Button
 v-if="['completed', 'failed', 'cancelled'].includes(graphStatus)"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="deleting"
 >
 <span v-if="deleting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--trash-2] mr-2" />
 只清图谱
 </Button>
 </AlertDialogTrigger>
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>确认只清空图谱数据？</AlertDialogTitle>
 <AlertDialogDescription>
 已构建的 symbols/imports/calls/endpoints 将被全部删除，向量索引和 FileIndex 保留。可点&quot;立即构建&quot;重新生成。
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel>取消</AlertDialogCancel>
 <AlertDialogAction:disabled="deleting" @click="triggerDelete">
 确认清空
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </div>
 </div>
 </div>
 </div>
</template>
