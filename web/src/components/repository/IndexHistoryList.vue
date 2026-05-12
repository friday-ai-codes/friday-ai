<script setup lang="ts">
import type { IndexHistoryItem, IndexHistoryResponse } from '~/api/repositories'
import type {
 IndexStreamEvent,
 IndexStreamRepositoryPayload,
} from '~/composables/useIndexProgressStream'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { connectIndexProgressStream } from '~/composables/useIndexProgressStream'
const props = defineProps<{
 repositoryId: string
 gitUrl?: string
}>
const loading = ref(true)
const history = ref<IndexHistoryResponse | null>(null)
const currentPage = ref(1)
const statusFilter = ref<string>('')
const pageSize = 5
// SSE 实时进度状态：repository 进度字段（merge 进当前 RUNNING 行）
const liveRepoProgress = ref<IndexStreamRepositoryPayload | null>(null)
// SSE 推来的 RUNNING IndexHistory（可能比 list 中的版本新 — 例如 indexer 拿到 diff
// 后立刻 partial-update 写入了 stats / changed_files）
const liveRunningHistory = ref<IndexHistoryItem | null>(null)
let streamController: AbortController | null = null
// SSE 失败兜底：dev 环境 vite proxy 偶发把长连接中断；
// 此时降级为 polling 列表（间接拿到 RUNNING 行的 stats / changed_files 更新）
let pollInterval: ReturnType<typeof setInterval> | null = null
// 是否展开"变更文件"细节（按 IndexHistory id 区分；运行中默认折叠避免 SSE 刷新刺眼）
const expandedItems = ref<Set<string>>(new Set)
function toggleExpanded(id: string) {
 const next = new Set(expandedItems.value)
 if (next.has(id))
 next.delete(id)
 else next.add(id)
 expandedItems.value = next
}
// 失败行"重试"按钮：触发当前正在禁用的 history id（防双击）
const retryingItemId = ref<string | null>(null)
async function retryFailed(item: IndexHistoryItem) {
 if (retryingItemId.value)
 return
 retryingItemId.value = item.id
 try {
 await repositoriesApi.triggerIndex(props.repositoryId)
 // 触发成功后刷新列表 → 该失败行后会出现一条新的 RUNNING 行 → SSE 自动开
 await loadHistory
 }
 catch {
 // ApiError 由全局拦截器提示，这里仅恢复按钮可点击状态
 }
 finally {
 retryingItemId.value = null
 }
}
// 筛选按钮配置
const filterButtons = [
 { status: 'pending', label: '等待中' },
 { status: 'running', label: '运行中' },
 { status: 'completed', label: '已完成' },
 { status: 'failed', label: '失败' },
]
const triggerLabels: Record<string, string> = {
 manual: '手动',
 webhook: 'Webhook',
 scheduled: '定时',
}
async function loadHistory {
 loading.value = true
 try {
 history.value = await repositoriesApi.getIndexHistory(props.repositoryId, {
 limit: pageSize,
 offset: (currentPage.value - 1) * pageSize,
 status: statusFilter.value || undefined,
 })
 }
 catch {
 // intentionally ignored
 }
 finally {
 loading.value = false
 }
}
function formatDate(dateStr: string | null) {
 if (!dateStr)
 return '-'
 return new Date(dateStr).toLocaleString('zh-CN')
}
function formatDuration(item: IndexHistoryItem) {
 if (!item.started_at || !item.finished_at)
 return '-'
 const ms = new Date(item.finished_at).getTime - new Date(item.started_at).getTime
 if (ms < 1000)
 return `${ms}ms`
 if (ms < 60000)
 return `${(ms / 1000).toFixed(1)}s`
 return `${(ms / 60000).toFixed(1)}min`
}
const totalPages = computed( => {
 if (!history.value)
 return 0
 return Math.ceil(history.value.total / pageSize)
})
function setFilter(status: string) {
 statusFilter.value = statusFilter.value === status ? '': status
 currentPage.value = 1
}
// 把 SSE 推来的 running_history 字段合并进当前 list 显示
// 思路：list 里的 RUNNING 行用 SSE 帧覆盖（id 相同则用 SSE 版本，因为更新更频繁）
const displayItems = computed<IndexHistoryItem>( => {
 const items = history.value?.items ??
 const live = liveRunningHistory.value
 if (!live)
 return items
 return items.map(it => (it.id === live.id ? { ...it, ...live }: it))
})
const hasRunningInList = computed( =>
 (history.value?.items ?? ).some(it => it.status === 'running'),
)
function progressForRunning(item: IndexHistoryItem) {
 // RUNNING 行的进度优先使用 SSE 推来的整体进度 — 与"代码索引"卡片同源
 if (item.status !== 'running')
 return null
 if (!liveRepoProgress.value)
 return null
 return liveRepoProgress.value
}
// 在 embedding/write 之前的阶段（克隆 / 对比 hash / 解析 / 图谱 / 收尾）没有
// 准确的数值进度 — 这时进度条改成 indeterminate 动画并隐藏百分比，避免长时间停留在 0%。
function isIndeterminateProgress(item: IndexHistoryItem): boolean {
 const p = progressForRunning(item)
 if (!p)
 return true
 // total_chunks 还没出来（解析前）→ 不确定阶段
 if ((p.index_total_chunks ?? 0) === 0)
 return true
 // total 有但 progress 还在 0% → 仍然在前置阶段
 return (p.overall_progress ?? 0) <= 0
}
function changedFilesOf(item: IndexHistoryItem) {
 return item.changed_files ?? { added:, modified:, deleted: }
}
function totalChangedCount(item: IndexHistoryItem) {
 const cf = changedFilesOf(item)
 return (
 (cf.added?.length ?? 0)
 + (cf.modified?.length ?? 0)
 + (cf.deleted?.length ?? 0)
 )
}
function startStream {
 if (streamController)
 return
 streamController = connectIndexProgressStream(props.repositoryId, {
 onEvent: (event: IndexStreamEvent) => {
 if (event.type === 'progress') {
 liveRepoProgress.value = event.repository
 liveRunningHistory.value = event.running_history
 // 当 SSE 反馈 history 已不在 RUNNING（或没有 running_history），
 // 安全做法是 refetch list 让 status badge / counts 同步到最终态
 if (event.running_history === null && hasRunningInList.value) {
 loadHistory
 }
 }
 else if (event.type === 'done') {
 stopAllProgressWatchers
 // 索引已结束 — 重新拉取列表把 RUNNING → COMPLETED/FAILED
 loadHistory
 }
 },
 onError: => {
 // SSE 断开 → 降级为 polling 列表，确保 RUNNING 行 stats 仍可刷新
 stopStream
 startPollingFallback
 },
 })
}
function stopStream {
 streamController?.abort
 streamController = null
 liveRepoProgress.value = null
 liveRunningHistory.value = null
}
// SSE 兜底 polling：每 3s 重新拉取列表（包含最新的 changed_files / stats）
function startPollingFallback {
 if (pollInterval)
 return
 pollInterval = setInterval(async => {
 await loadHistory
 if (!hasRunningInList.value)
 stopAllProgressWatchers
 }, 3000)
}
function stopPollingFallback {
 if (pollInterval) {
 clearInterval(pollInterval)
 pollInterval = null
 }
}
function stopAllProgressWatchers {
 stopStream
 stopPollingFallback
}
watch(hasRunningInList, (running) => {
 if (running)
 startStream
 else stopAllProgressWatchers
}, { immediate: false })
watch([currentPage, statusFilter], loadHistory)
onMounted(async => {
 await loadHistory
 if (hasRunningInList.value)
 startStream
})
onBeforeUnmount( => {
 stopAllProgressWatchers
})
</script>
<template>
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--history] text-primary" />
 <h3 class="text-sm font-semibold">
 索引历史
 </h3>
 </div>
 <p class="text-xs text-muted-foreground mt-0.5">
 查看每次索引操作的详细记录
 </p>
 </div>
 <div class="">
 <!-- 状态筛选 -->
 <div class="flex gap-2 mb-4">
 <Button
 v-for="btn in filterButtons":key="btn.status":variant="statusFilter === btn.status ? 'default': 'outline'"
 size="sm"
 class=" text-xs"
 @click="setFilter(btn.status)"
 >
 {{ btn.label }}
 </Button>
 </div>
 <!-- 加载状态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground">加载历史记录...</span>
 </div>
 <!-- 无记录 -->
 <div v-else-if="!history || history.items.length === 0" class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--history] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground">
 {{ statusFilter ? '该状态下暂无记录': '暂无索引历史' }}
 </p>
 </div>
 <!-- 历史列表 -->
 <div v-else class="space-y-3">
 <div
 v-for="item in displayItems":key="item.id"
 class=" rounded-xl border border-border/50 bg-muted/20 hover:bg-muted/40 transition-colors space-y-3"
 >
 <!-- 头部：状态 + 触发方式 + 时间 -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <StatusBadge type="index":status="item.status" />
 <Badge variant="outline" class="bg-muted/50">
 {{ triggerLabels[item.trigger_type] || item.trigger_type }}
 </Badge>
 </div>
 <span class="text-xs text-muted-foreground">{{ formatDate(item.created_at) }}</span>
 </div>
 <!-- RUNNING 行：实时进度条 + stage 文案 -->
 <div v-if="item.status === 'running' && progressForRunning(item)" class="space-y-1.5">
 <div class="flex items-center justify-between text-xs">
 <span class="text-muted-foreground inline-flex items-center gap-1.5">
 <span class="icon-[lucide--loader-circle] animate-spin text-primary" />
 {{ progressForRunning(item)?.overall_stage || '索引中...' }}
 </span>
 <span
 v-if="!isIndeterminateProgress(item)"
 class="font-mono tabular-nums text-primary"
 >
 {{ progressForRunning(item)?.overall_progress ?? 0 }}%
 </span>
 </div>
 <div class=".5 w-full overflow-hidden rounded-full bg-muted relative">
 <!-- 确定进度（embedding / write 阶段）：按比例填充 -->
 <div
 v-if="!isIndeterminateProgress(item)"
 class="h-full bg-primary transition-[width] duration-300 ease-out":style="{ width: `${progressForRunning(item)?.overall_progress ?? 0}%` }"
 />
 <!-- 不确定进度（克隆 / 对比 hash / 解析 / 图谱）：滑块动画 -->
 <div
 v-else
 class="absolute inset-y-0 w-1/3 bg-primary rounded-full"
 style="animation: index-indeterminate 1.6s ease-in-out infinite;"
 />
 </div>
 </div>
 <!-- 文件变更统计 -->
 <div
 v-if="item.files_added || item.files_modified || item.files_deleted"
 class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs"
 >
 <span v-if="item.files_added" class="text-emerald-600">
 <span class="icon-[lucide--plus] mr-0.5" />{{ item.files_added }} 新增
 </span>
 <span v-if="item.files_modified" class="text-amber-600">
 <span class="icon-[lucide--pencil] mr-0.5" />{{ item.files_modified }} 修改
 </span>
 <span v-if="item.files_deleted" class="text-destructive">
 <span class="icon-[lucide--minus] mr-0.5" />{{ item.files_deleted }} 删除
 </span>
 <Button
 v-if="totalChangedCount(item) > 0 && item.changed_files"
 variant="ghost"
 size="sm"
 class=" px-2 text-xs text-muted-foreground"
 @click="toggleExpanded(item.id)"
 >
 <span:class="[
 'icon-[lucide--chevron-right] mr-0.5 transition-transform',
 expandedItems.has(item.id) ? 'rotate-90': '',
 ]"
 />
 {{ expandedItems.has(item.id) ? '收起': '查看变更文件' }}
 </Button>
 </div>
 <!-- 变更文件列表（按状态分组） -->
 <div
 v-if="expandedItems.has(item.id) && item.changed_files"
 class="rounded-lg border border-border/50 bg-muted/30 px-3 py-2 text-xs space-y-2 font-mono"
 >
 <div v-if="item.changed_files.added?.length">
 <p class="text-emerald-600 mb-1 font-sans">
 新增 {{ item.changed_files.added.length }} 个文件
 </p>
 <ul class="space-y-0.5 text-muted-foreground">
 <li v-for="path in item.changed_files.added":key="`a-${path}`" class="truncate">
 + {{ path }}
 </li>
 </ul>
 </div>
 <div v-if="item.changed_files.modified?.length">
 <p class="text-amber-600 mb-1 font-sans">
 修改 {{ item.changed_files.modified.length }} 个文件
 </p>
 <ul class="space-y-0.5 text-muted-foreground">
 <li v-for="path in item.changed_files.modified":key="`m-${path}`" class="truncate">
 ~ {{ path }}
 </li>
 </ul>
 </div>
 <div v-if="item.changed_files.deleted?.length">
 <p class="text-destructive mb-1 font-sans">
 删除 {{ item.changed_files.deleted.length }} 个文件
 </p>
 <ul class="space-y-0.5 text-muted-foreground">
 <li v-for="path in item.changed_files.deleted":key="`d-${path}`" class="truncate">
 - {{ path }}
 </li>
 </ul>
 </div>
 </div>
 <!-- SHA 范围 + 耗时 -->
 <div class="flex items-center justify-between text-xs text-muted-foreground">
 <span v-if="item.from_sha || item.to_sha" class="font-mono flex items-center gap-1">
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <span>{{ item.from_sha?.slice(0, 7) || '---' }}</span>
 </TooltipTrigger>
 <TooltipContent v-if="item.from_sha">
 {{ item.from_sha }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <span>→</span>
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <span>{{ item.to_sha?.slice(0, 7) || '---' }}</span>
 </TooltipTrigger>
 <TooltipContent v-if="item.to_sha">
 {{ item.to_sha }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </span>
 <span v-else />
 <div class="flex items-center gap-1">
 <span v-if="item.started_at && item.finished_at">
 <span class="icon-[lucide--clock] mr-1" />{{ formatDuration(item) }}
 </span>
 <!--：在远端查看此 commit（aria-label work item §7 锁定文案） -->
 <Button
 v-if="item.to_sha && gitUrl"
 variant="ghost"
 size="sm"
 class=" w-7 "
 as="a":href="`${gitUrl.replace(/\.git$/, '')}/commit/${item.to_sha}`"
 target="_blank"
 rel="noopener noreferrer"
 aria-label="在远端查看此 commit"
 >
 <span class="icon-[lucide--external-link] text-xs" />
 </Button>
 </div>
 </div>
 <!-- 摘要/错误 -->
 <p v-if="item.summary_text" class="text-xs text-muted-foreground bg-muted/30 rounded-lg px-3 py-2">
 {{ item.summary_text }}
 </p>
 <div
 v-if="item.error_message && item.status === 'failed'"
 class="rounded-lg bg-destructive/5 px-3 py-2 space-y-2"
 >
 <p class="text-xs text-destructive">
 {{ item.error_message }}
 </p>
 <Button
 variant="outline"
 size="sm"
 class=" text-xs":disabled="retryingItemId === item.id"
 @click="retryFailed(item)"
 >
 <span:class="[
 'mr-1',
 retryingItemId === item.id
 ? 'icon-[lucide--loader-circle] animate-spin': 'icon-[lucide--rotate-ccw]',
 ]"
 />
 {{ retryingItemId === item.id ? '正在触发...': '重试' }}
 </Button>
 </div>
 </div>
 <!-- 分页 -->
 <div v-if="totalPages > 1" class="flex items-center justify-between pt-2">
 <span class="text-xs text-muted-foreground">共 {{ history.total }} 条记录</span>
 <div class="flex items-center gap-1">
 <Button
 variant="outline"
 size="sm"
 class=" w-7 ":disabled="currentPage <= 1"
 @click="currentPage--"
 >
 <span class="icon-[lucide--chevron-left]" />
 </Button>
 <span class="text-xs text-muted-foreground px-2">{{ currentPage }} / {{ totalPages }}</span>
 <Button
 variant="outline"
 size="sm"
 class=" w-7 ":disabled="currentPage >= totalPages"
 @click="currentPage++"
 >
 <span class="icon-[lucide--chevron-right]" />
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
<style scoped>
/*
 * Indeterminate 进度条动画：滑块从左侧滑出右侧，循环出现 — 用在
 * 索引前置阶段（克隆 / 对比 hash / 解析 / 图谱 / 收尾）这种没有数值进度
 * 的场景，比 0% 长时间停滞要友好。
 */
@keyframes index-indeterminate {
 0% {
 left: -33%;
 }
 100% {
 left: 100%;
 }
}
</style>
