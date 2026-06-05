<script setup lang="ts">
import type { IndexHistoryItem, IndexHistoryResponse } from '~/api/repositories'
import type {
  IndexStreamEvent,
  IndexStreamRepositoryPayload,
} from '~/composables/useIndexProgressStream'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import StatusBadge from '~/components/common/StatusBadge.vue'
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
}>()

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
const expandedItems = ref<Set<string>>(new Set())

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
    await loadHistory()
  }
  catch {
    // ApiError 由全局拦截器提示，这里仅恢复按钮可点击状态
  }
  finally {
    retryingItemId.value = null
  }
}

// 筛选按钮配置 — iconClass 写成完整字面量，unocss 才能在静态分析阶段扫到
const filterButtons = [
  { status: '', label: '全部', iconClass: 'icon-[lucide--layers]' },
  { status: 'pending', label: '等待中', iconClass: 'icon-[lucide--clock]' },
  { status: 'running', label: '运行中', iconClass: 'icon-[lucide--loader-2]' },
  { status: 'completed', label: '已完成', iconClass: 'icon-[lucide--check-circle]' },
  { status: 'failed', label: '失败', iconClass: 'icon-[lucide--x-circle]' },
]

const triggerLabels: Record<string, string> = {
  manual: '手动',
  webhook: 'Webhook',
  scheduled: '定时',
}

// item 状态对应 timeline 圆点颜色（与 StatusBadge variant 同源 — 仅做视觉锚点，
// 不替代 Badge 的语义。圆点比色条更克制、更"设计师"，避免每行一根红条的告警感）
function statusDotClass(status: string): string {
  switch (status) {
    case 'completed':
    case 'indexed':
      return 'bg-emerald-500'
    case 'running':
    case 'indexing':
      return 'bg-blue-500'
    case 'failed':
      return 'bg-destructive'
    case 'pending':
    case 'not_indexed':
      return 'bg-amber-400'
    case 'cancelled':
      return 'bg-muted-foreground/40'
    default:
      return 'bg-muted-foreground/30'
  }
}

async function loadHistory() {
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
  const ms = new Date(item.finished_at).getTime() - new Date(item.started_at).getTime()
  if (ms < 1000)
    return `${ms}ms`
  if (ms < 60000)
    return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

const totalPages = computed(() => {
  if (!history.value)
    return 0
  return Math.ceil(history.value.total / pageSize)
})

function setFilter(status: string) {
  statusFilter.value = statusFilter.value === status ? '' : status
  currentPage.value = 1
}

// 把 SSE 推来的 running_history 字段合并进当前 list 显示
// 思路：list 里的 RUNNING 行用 SSE 帧覆盖（id 相同则用 SSE 版本，因为更新更频繁）
const displayItems = computed<IndexHistoryItem[]>(() => {
  const items = history.value?.items ?? []
  const live = liveRunningHistory.value
  if (!live)
    return items
  return items.map(it => (it.id === live.id ? { ...it, ...live } : it))
})

const hasRunningInList = computed(() =>
  (history.value?.items ?? []).some(it => it.status === 'running'),
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

// 行级 diff 显示（Pitfall 6 前端镜像）：
// null / undefined（不可计算：全量索引 / shallow 加深失败）→ "—"，
// 真实数字（含 0：无增删或二进制文件）→ 原值字符串，二者严格不混。
function linesDisplay(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${v}`
}

// per-run delta 段是否有可展示内容：
// 任一字段已回填（非 undefined）即显示；老行未回填（全 undefined）则整段隐藏，
// 避免渲染一排无意义的 0。
function hasPerRunDelta(item: IndexHistoryItem): boolean {
  return (
    item.symbols_added !== undefined
    || item.calls_added !== undefined
    || item.imports_added !== undefined
    || item.chunk_edges_added !== undefined
  )
}

// 行级 diff 段是否有可展示内容：
// 任一字段已回填（含 null=不可计算，须显示 "—"）即显示。
function hasLineDiff(item: IndexHistoryItem): boolean {
  return item.lines_added !== undefined || item.lines_deleted !== undefined
}

function changedFilesOf(item: IndexHistoryItem) {
  return item.changed_files ?? { added: [], modified: [], deleted: [] }
}

function totalChangedCount(item: IndexHistoryItem) {
  const cf = changedFilesOf(item)
  return (
    (cf.added?.length ?? 0)
    + (cf.modified?.length ?? 0)
    + (cf.deleted?.length ?? 0)
  )
}

function startStream() {
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
          loadHistory()
        }
      }
      else if (event.type === 'done') {
        stopAllProgressWatchers()
        // 索引已结束 — 重新拉取列表把 RUNNING → COMPLETED/FAILED
        loadHistory()
      }
    },
    onError: () => {
      // SSE 断开 → 降级为 polling 列表，确保 RUNNING 行 stats 仍可刷新
      stopStream()
      startPollingFallback()
    },
  })
}

function stopStream() {
  streamController?.abort()
  streamController = null
  liveRepoProgress.value = null
  liveRunningHistory.value = null
}

// SSE 兜底 polling：每 3s 重新拉取列表（包含最新的 changed_files / stats）
function startPollingFallback() {
  if (pollInterval)
    return
  pollInterval = setInterval(async () => {
    await loadHistory()
    if (!hasRunningInList.value)
      stopAllProgressWatchers()
  }, 3000)
}

function stopPollingFallback() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

function stopAllProgressWatchers() {
  stopStream()
  stopPollingFallback()
}

watch(hasRunningInList, (running) => {
  if (running)
    startStream()
  else stopAllProgressWatchers()
}, { immediate: false })

watch([currentPage, statusFilter], loadHistory)
onMounted(async () => {
  await loadHistory()
  if (hasRunningInList.value)
    startStream()
})

onBeforeUnmount(() => {
  stopAllProgressWatchers()
})
</script>

<template>
  <div class="card">
    <div class="px-4 py-2.5 border-b border-border/50">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--history] text-primary text-sm" />
        <h3 class="text-xs font-semibold">
          索引历史
        </h3>
        <span class="text-[11px] text-muted-foreground">每次索引操作的详细记录</span>
      </div>
    </div>
    <div class="p-3">
      <!-- 状态筛选 — segmented 风格紧凑筛选条 -->
      <div class="inline-flex items-center gap-0.5 p-0.5 mb-3 rounded-md bg-muted/40 border border-border/40">
        <button
          v-for="btn in filterButtons"
          :key="btn.status || 'all'"
          type="button"
          class="inline-flex items-center gap-1 h-6 px-2 rounded text-[11px] font-medium transition-all" :class="[
            statusFilter === btn.status
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          ]"
          @click="setFilter(btn.status)"
        >
          <span class="text-[11px]" :class="[btn.iconClass]" />
          {{ btn.label }}
        </button>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center gap-2 py-5">
        <span class="icon-[lucide--loader-circle] text-base text-primary animate-spin" />
        <span class="text-muted-foreground text-xs">加载历史记录...</span>
      </div>

      <!-- 无记录 -->
      <div v-else-if="!history || history.items.length === 0" class="text-center py-6">
        <div class="inline-flex p-2 rounded-full bg-muted/50 mb-1.5">
          <span class="icon-[lucide--history] text-xl text-muted-foreground" />
        </div>
        <p class="text-xs text-muted-foreground">
          {{ statusFilter ? '该状态下暂无记录' : '暂无索引历史' }}
        </p>
      </div>

      <!-- 历史列表 — 真·timeline：贯穿轨道线 + 状态点，告别"每行红条" -->
      <ol v-else class="timeline relative">
        <li
          v-for="(item, idx) in displayItems"
          :key="item.id"
          class="timeline-item group relative pl-7 pr-1"
          :class="idx === displayItems.length - 1 ? 'pb-0.5' : 'pb-2.5'"
        >
          <!-- 轨道线（除最后一项外向下延伸） -->
          <span
            v-if="idx !== displayItems.length - 1"
            class="absolute left-2.5 top-4 bottom-0 w-px bg-border/70"
            aria-hidden="true"
          />
          <!-- 状态圆点（ring-card 把轨道线"打断"，形成节点视觉） -->
          <span
            class="absolute left-2.5 top-1.5 -translate-x-1/2 z-10 flex items-center justify-center"
            aria-hidden="true"
          >
            <span
              class="block w-2 h-2 rounded-full ring-[3px] ring-card" :class="[
                statusDotClass(item.status),
                item.status === 'running'
                  ? 'shadow-[0_0_0_3px_rgba(59,130,246,0.18)] animate-pulse'
                  : '',
              ]"
            />
          </span>

          <!-- 内容容器（hover 仅做轻微底色变化，不抢戏） -->
          <div class="-mx-1.5 px-1.5 py-1 rounded-md group-hover:bg-muted/30 transition-colors space-y-1">
            <!-- 顶部 meta row：状态 / 触发 / SHA  vs  耗时 / 时间 / 外链 -->
            <div class="flex items-start justify-between gap-3 flex-wrap">
              <div class="flex items-center gap-2 min-w-0 flex-wrap text-xs">
                <StatusBadge type="index" :status="item.status" size="sm" />
                <span class="text-muted-foreground/50">·</span>
                <span class="inline-flex items-center gap-1 text-muted-foreground">
                  <span class="icon-[lucide--zap] text-[10px]" />
                  {{ triggerLabels[item.trigger_type] || item.trigger_type }}
                </span>
                <!-- SHA 范围 — 只展示 to，from 用 → 隐喻起点（更克制） -->
                <template v-if="item.from_sha || item.to_sha">
                  <span class="text-muted-foreground/50">·</span>
                  <span class="hidden sm:inline-flex items-center gap-1 font-mono text-muted-foreground">
                    <TooltipProvider :delay-duration="300">
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <span>{{ item.from_sha?.slice(0, 7) || '———' }}</span>
                        </TooltipTrigger>
                        <TooltipContent v-if="item.from_sha">
                          {{ item.from_sha }}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <span class="icon-[lucide--arrow-right] text-[10px] opacity-50" />
                    <TooltipProvider :delay-duration="300">
                      <Tooltip>
                        <TooltipTrigger as-child>
                          <span class="text-foreground/80">{{ item.to_sha?.slice(0, 7) || '———' }}</span>
                        </TooltipTrigger>
                        <TooltipContent v-if="item.to_sha">
                          {{ item.to_sha }}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </span>
                </template>
              </div>
              <div class="flex items-center gap-2 text-xs text-muted-foreground/80 shrink-0 tabular-nums">
                <span v-if="item.started_at && item.finished_at" class="font-mono">
                  {{ formatDuration(item) }}
                </span>
                <span class="opacity-30">·</span>
                <time>{{ formatDate(item.created_at) }}</time>
                <Button
                  v-if="item.to_sha && gitUrl"
                  variant="ghost"
                  size="sm"
                  class="h-6 w-6 p-0 -mr-1 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
                  as="a"
                  :href="`${gitUrl.replace(/\.git$/, '')}/commit/${item.to_sha}`"
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="在远端查看此 commit"
                >
                  <span class="icon-[lucide--external-link] text-xs" />
                </Button>
              </div>
            </div>

            <!-- RUNNING 行：进度条贴在 meta 下方，极细一根，不抢戏 -->
            <div v-if="item.status === 'running' && progressForRunning(item)" class="space-y-1 pt-0.5">
              <div class="flex items-center justify-between text-xs">
                <span class="text-muted-foreground inline-flex items-center gap-1.5">
                  <span class="icon-[lucide--loader-circle] animate-spin text-blue-500 text-[11px]" />
                  {{ progressForRunning(item)?.overall_stage || '索引中...' }}
                </span>
                <span
                  v-if="!isIndeterminateProgress(item)"
                  class="font-mono tabular-nums text-blue-600/90 font-medium"
                >
                  {{ progressForRunning(item)?.overall_progress ?? 0 }}%
                </span>
              </div>
              <div class="h-0.5 w-full overflow-hidden rounded-full bg-border/60 relative">
                <div
                  v-if="!isIndeterminateProgress(item)"
                  class="h-full bg-blue-500 transition-[width] duration-300 ease-out"
                  :style="{ width: `${progressForRunning(item)?.overall_progress ?? 0}%` }"
                />
                <div
                  v-else
                  class="absolute inset-y-0 w-1/3 bg-blue-500 rounded-full"
                  style="animation: index-indeterminate 1.6s ease-in-out infinite;"
                />
              </div>
            </div>

            <!-- 文件变更统计（紧凑 inline，符号代替图标，更轻） -->
            <div
              v-if="item.files_added || item.files_modified || item.files_deleted"
              class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
            >
              <span v-if="item.files_added" class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-emerald-600 font-medium">+{{ item.files_added }}</span>
                <span>新增</span>
              </span>
              <span v-if="item.files_modified" class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-amber-600 font-medium">~{{ item.files_modified }}</span>
                <span>修改</span>
              </span>
              <span v-if="item.files_deleted" class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-destructive font-medium">−{{ item.files_deleted }}</span>
                <span>删除</span>
              </span>
              <button
                v-if="totalChangedCount(item) > 0 && item.changed_files"
                type="button"
                class="inline-flex items-center gap-1 h-5 px-1 -mx-0.5 rounded text-muted-foreground/80 hover:text-foreground hover:bg-muted/50 transition-colors"
                @click="toggleExpanded(item.id)"
              >
                <span
                  class="icon-[lucide--chevron-right] text-[10px] transition-transform" :class="[
                    expandedItems.has(item.id) ? 'rotate-90' : '',
                  ]"
                />
                {{ expandedItems.has(item.id) ? '收起' : '查看变更文件' }}
              </button>
            </div>

            <!-- ：per-run delta 段（本次索引图谱实体，区别于累计
                 edge_count；读 running_history 携带的 295-01 字段，RUNNING 行经
                 liveRunningHistory merge 实时刷新）。
                 文案用「本次索引」中性措辞（code-review 295 H1）：符号/调用/import 取自
                 write_bundle 本次写入/重建量（增量重建文件含其既有实体，非去重净增），
                 仅 chunk edge 为去重净新增，避免把重建量误读为净新增。 -->
            <div
              v-if="hasPerRunDelta(item)"
              class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
            >
              <span class="text-muted-foreground/70">本次索引</span>
              <span class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-emerald-600 font-medium">{{ item.symbols_added ?? 0 }}</span>
                <span>符号</span>
              </span>
              <span class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-emerald-600 font-medium">{{ item.calls_added ?? 0 }}</span>
                <span>调用</span>
              </span>
              <span class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-emerald-600 font-medium">{{ item.imports_added ?? 0 }}</span>
                <span>import</span>
              </span>
              <span class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-emerald-600 font-medium">{{ item.chunk_edges_added ?? 0 }}</span>
                <span>chunk edge</span>
              </span>
            </div>

            <!-- ：行级 diff 段（+N −N 行 / N 文件重索引；
                 null=不可计算 → linesDisplay 显示 "—"，真实 0 显示 "0"，Pitfall 6） -->
            <div
              v-if="hasLineDiff(item)"
              class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"
            >
              <span class="inline-flex items-center gap-1 tabular-nums">
                <span class="text-emerald-600 font-medium">+{{ linesDisplay(item.lines_added) }}</span>
                <span class="text-destructive font-medium">−{{ linesDisplay(item.lines_deleted) }}</span>
                <span>行</span>
              </span>
              <span v-if="totalChangedCount(item) > 0" class="inline-flex items-center gap-1 tabular-nums">
                <span class="font-medium">{{ totalChangedCount(item) }}</span>
                <span>文件重索引</span>
              </span>
            </div>

            <!-- 变更文件列表（按状态分组，无边框、靠左缩进，像 git status 输出） -->
            <div
              v-if="expandedItems.has(item.id) && item.changed_files"
              class="pl-2 border-l border-border/60 ml-0.5 text-xs space-y-2"
            >
              <div v-if="item.changed_files.added?.length">
                <p class="text-emerald-600/90 mb-1 text-[11px] font-medium uppercase tracking-wide">
                  新增 {{ item.changed_files.added.length }} 个文件
                </p>
                <ul class="space-y-0.5 text-muted-foreground font-mono">
                  <li v-for="path in item.changed_files.added" :key="`a-${path}`" class="truncate">
                    <span class="text-emerald-600/70">+</span> {{ path }}
                  </li>
                </ul>
              </div>
              <div v-if="item.changed_files.modified?.length">
                <p class="text-amber-600/90 mb-1 text-[11px] font-medium uppercase tracking-wide">
                  修改 {{ item.changed_files.modified.length }} 个文件
                </p>
                <ul class="space-y-0.5 text-muted-foreground font-mono">
                  <li v-for="path in item.changed_files.modified" :key="`m-${path}`" class="truncate">
                    <span class="text-amber-600/70">~</span> {{ path }}
                  </li>
                </ul>
              </div>
              <div v-if="item.changed_files.deleted?.length">
                <p class="text-destructive/90 mb-1 text-[11px] font-medium uppercase tracking-wide">
                  删除 {{ item.changed_files.deleted.length }} 个文件
                </p>
                <ul class="space-y-0.5 text-muted-foreground font-mono">
                  <li v-for="path in item.changed_files.deleted" :key="`d-${path}`" class="truncate">
                    <span class="text-destructive/70">−</span> {{ path }}
                  </li>
                </ul>
              </div>
            </div>

            <!-- 摘要 -->
            <p v-if="item.summary_text" class="text-xs text-muted-foreground leading-relaxed">
              {{ item.summary_text }}
            </p>

            <!-- 错误信息（无色块、无边框；纯 inline "批注"风格 + 文字按钮） -->
            <div
              v-if="item.error_message && item.status === 'failed'"
              class="flex items-start justify-between gap-3"
            >
              <p class="text-xs text-destructive/85 flex-1 min-w-0 leading-relaxed wrap-break-word inline-flex items-start gap-1.5">
                <span class="icon-[lucide--circle-alert] text-destructive/70 shrink-0 text-[12px] mt-px" />
                <span>{{ item.error_message }}</span>
              </p>
              <button
                type="button"
                class="inline-flex items-center gap-1 h-6 px-1.5 -mx-0.5 rounded text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/8 transition-colors shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                :disabled="retryingItemId === item.id"
                @click="retryFailed(item)"
              >
                <span
                  class="text-[11px]" :class="[
                    retryingItemId === item.id
                      ? 'icon-[lucide--loader-circle] animate-spin'
                      : 'icon-[lucide--rotate-ccw]',
                  ]"
                />
                {{ retryingItemId === item.id ? '触发中' : '重试' }}
              </button>
            </div>
          </div>
        </li>
      </ol>

      <!-- 分页 -->
      <div v-if="history && totalPages > 1" class="flex items-center justify-between pt-3 mt-3 border-t border-border/40">
        <span class="text-xs text-muted-foreground">共 {{ history.total }} 条记录</span>
        <div class="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            class="h-7 w-7 p-0"
            :disabled="currentPage <= 1"
            @click="currentPage--"
          >
            <span class="icon-[lucide--chevron-left]" />
          </Button>
          <span class="text-xs text-muted-foreground px-2 tabular-nums">{{ currentPage }} / {{ totalPages }}</span>
          <Button
            variant="outline"
            size="sm"
            class="h-7 w-7 p-0"
            :disabled="currentPage >= totalPages"
            @click="currentPage++"
          >
            <span class="icon-[lucide--chevron-right]" />
          </Button>
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
