<script setup lang="ts">
import type { ActiveTasksResponse } from '~/api/system'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { cancelRepoIndex, cancelRepoSummary, getActiveTasks } from '~/api/system'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

definePage({
  meta: { requiresAdmin: true },
})

const REFRESH_MS = 4000
const PAGE_SIZE = 20

const { handleError } = useErrorHandler()
const { success } = useToast()

const data = ref<ActiveTasksResponse | null>(null)
const loading = ref(true)
const error = ref('')
const lastUpdated = ref('')
const autoRefresh = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

// 筛选 + 分页
const statusFilter = ref<'all' | 'pending' | 'running'>('all')
const indexingOffset = ref(0)
const summaryOffset = ref(0)
const cancelling = ref<Set<string>>(new Set())

async function load(silent = false) {
  if (!silent)
    loading.value = true
  try {
    data.value = await getActiveTasks({
      status: statusFilter.value,
      limit: PAGE_SIZE,
      // 索引/建立知识共用一个 offset 控件会割裂；这里分别传，用较大者覆盖即可。
      // 后端两类各自 offset 独立分页，这里以两个区块独立翻页。
      offset: 0,
    })
    error.value = ''
    lastUpdated.value = new Date().toLocaleTimeString()
  }
  catch (e: any) {
    error.value = e?.detail || e?.message || '加载失败'
  }
  finally {
    loading.value = false
  }
}

// 分区块独立翻页：直接按 type 拉取对应区块。
async function loadIndexing() {
  const res = await getActiveTasks({ type: 'indexing', status: statusFilter.value, limit: PAGE_SIZE, offset: indexingOffset.value })
  if (data.value)
    data.value.indexing = res.indexing
}
async function loadSummary() {
  const res = await getActiveTasks({ type: 'summary', status: statusFilter.value, limit: PAGE_SIZE, offset: summaryOffset.value })
  if (data.value)
    data.value.summary = res.summary
}

function onFilterChange(value: any) {
  statusFilter.value = (typeof value === 'string' ? value : 'all') as typeof statusFilter.value
  indexingOffset.value = 0
  summaryOffset.value = 0
  load(true)
}

function startTimer() {
  stopTimer()
  if (autoRefresh.value)
    timer = setInterval(() => load(true), REFRESH_MS)
}
function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function toggleAuto() {
  autoRefresh.value = !autoRefresh.value
  startTimer()
}

onMounted(() => {
  load()
  startTimer()
})
onUnmounted(stopTimer)

async function terminateIndexing(repoId: string, name: string) {
  cancelling.value.add(`idx-${repoId}`)
  try {
    await cancelRepoIndex(repoId)
    success('已终止', `已停止索引：${name}`)
    await load(true)
  }
  catch (e) {
    handleError(e, '终止索引')
  }
  finally {
    cancelling.value.delete(`idx-${repoId}`)
  }
}

async function terminateSummary(repoId: string, name: string) {
  cancelling.value.add(`sum-${repoId}`)
  try {
    await cancelRepoSummary(repoId)
    success('已终止', `已停止建立知识：${name}`)
    await load(true)
  }
  catch (e) {
    handleError(e, '终止建立知识')
  }
  finally {
    cancelling.value.delete(`sum-${repoId}`)
  }
}

function isCancelling(prefix: string, repoId: string) {
  return cancelling.value.has(`${prefix}-${repoId}`)
}

// durable 队列按 queue 透视：{ queue: { status: count } }
const queuePivot = computed<Record<string, Record<string, number>>>(() => {
  const out: Record<string, Record<string, number>> = {}
  for (const row of data.value?.queue.by_queue_status ?? []) {
    out[row.queue] = out[row.queue] || {}
    out[row.queue][row.status] = row.count
  }
  return out
})

function pct(p: number, t: number): number {
  if (!t || t <= 0)
    return 0
  return Math.min(100, Math.round((p / t) * 100))
}

const indexingHasMore = computed(() => !!data.value && data.value.indexing.count > indexingOffset.value + (data.value.indexing.items.length))
const summaryHasMore = computed(() => !!data.value && data.value.summary.count > summaryOffset.value + (data.value.summary.items.length))

function indexingNext() {
  indexingOffset.value += PAGE_SIZE
  loadIndexing()
}
function indexingPrev() {
  indexingOffset.value = Math.max(0, indexingOffset.value - PAGE_SIZE)
  loadIndexing()
}
function summaryNext() {
  summaryOffset.value += PAGE_SIZE
  loadSummary()
}
function summaryPrev() {
  summaryOffset.value = Math.max(0, summaryOffset.value - PAGE_SIZE)
  loadSummary()
}
</script>

<template>
  <div class="p-6 space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-lg font-semibold text-foreground">
          任务中心
        </h1>
        <p class="text-xs text-muted-foreground mt-0.5">
          当前排队中 / 进行中的后台任务：代码索引、建立知识、durable 队列（仅系统管理员）
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Select :model-value="statusFilter" @update:model-value="onFilterChange">
          <SelectTrigger class="h-9 w-[130px] rounded-lg bg-background/90">
            <span class="icon-[lucide--filter] mr-1.5 text-sm text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              全部状态
            </SelectItem>
            <SelectItem value="pending">
              排队中
            </SelectItem>
            <SelectItem value="running">
              进行中
            </SelectItem>
          </SelectContent>
        </Select>
        <span v-if="lastUpdated" class="text-xs text-muted-foreground">更新于 {{ lastUpdated }}</span>
        <Button size="sm" variant="outline" @click="toggleAuto">
          {{ autoRefresh ? '暂停自动刷新' : '开启自动刷新' }}
        </Button>
        <Button size="sm" variant="outline" @click="() => load()">
          刷新
        </Button>
      </div>
    </div>

    <LoadingState v-if="loading && !data" />
    <div v-else-if="error" class="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
      {{ error }}
    </div>

    <template v-else-if="data">
      <!-- durable 队列深度 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--layers] w-4 h-4" /> 持久化队列（索引 / 图谱 / 建立知识 / 页面）
        </h2>
        <div class="rounded-lg border border-border divide-y divide-border">
          <div v-if="Object.keys(queuePivot).length === 0" class="p-4 text-sm text-muted-foreground">
            队列为空
          </div>
          <div
            v-for="(statuses, queue) in queuePivot"
            :key="queue"
            class="flex items-center gap-3 p-3 text-sm"
          >
            <span class="w-32 shrink-0 font-mono text-xs text-muted-foreground">{{ queue }}</span>
            <span
              v-for="(count, st) in statuses"
              :key="st"
              class="rounded px-2 py-0.5 text-xs bg-muted text-foreground"
            >{{ st }}: {{ count }}</span>
          </div>
        </div>
      </section>

      <!-- 正在索引的仓库 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--database] w-4 h-4" /> 正在索引（{{ data.indexing.count }}）
        </h2>
        <div class="rounded-lg border border-border divide-y divide-border">
          <div v-if="data.indexing.items.length === 0" class="p-4 text-sm text-muted-foreground">
            暂无正在索引的仓库
          </div>
          <div
            v-for="r in data.indexing.items"
            :key="r.repository_id"
            class="flex items-center gap-3 p-3 text-sm"
          >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="truncate font-medium text-foreground">{{ r.name }}</span>
                <span v-for="s in r.spaces" :key="s.id" class="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{{ s.name }}</span>
              </div>
              <div class="text-xs text-muted-foreground mt-0.5">
                {{ r.stage || '索引中' }}
                <span v-if="r.files_total > 0" class="tabular-nums">· {{ r.files_processed }}/{{ r.files_total }}（{{ pct(r.files_processed, r.files_total) }}%）</span>
              </div>
            </div>
            <RouterLink
              :to="`/repositories/${r.repository_id}?tab=indexing`"
              class="shrink-0 text-xs text-primary hover:underline"
            >
              查看仓库
            </RouterLink>
            <Button
              size="sm"
              variant="outline"
              :disabled="isCancelling('idx', r.repository_id)"
              class="shrink-0"
              @click="terminateIndexing(r.repository_id, r.name)"
            >
              <span class="icon-[lucide--circle-stop] mr-1 text-destructive" />
              终止
            </Button>
          </div>
        </div>
        <div v-if="indexingOffset > 0 || indexingHasMore" class="flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" :disabled="indexingOffset === 0" @click="indexingPrev">
            上一页
          </Button>
          <Button size="sm" variant="ghost" :disabled="!indexingHasMore" @click="indexingNext">
            下一页
          </Button>
        </div>
      </section>

      <!-- 建立知识排队 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--sparkles] w-4 h-4" /> 建立知识（{{ data.summary.count }}）
        </h2>
        <div class="rounded-lg border border-border divide-y divide-border">
          <div v-if="data.summary.items.length === 0" class="p-4 text-sm text-muted-foreground">
            暂无排队/进行中的建立知识任务
          </div>
          <div
            v-for="r in data.summary.items"
            :key="r.repository_id"
            class="flex items-center gap-3 p-3 text-sm"
          >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="truncate font-medium text-foreground">{{ r.name }}</span>
                <span v-for="s in r.spaces" :key="s.id" class="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">{{ s.name }}</span>
              </div>
            </div>
            <span class="rounded px-2 py-0.5 text-xs bg-muted text-foreground shrink-0">{{ r.status }}</span>
            <RouterLink
              :to="`/repositories/${r.repository_id}`"
              class="shrink-0 text-xs text-primary hover:underline"
            >
              查看仓库
            </RouterLink>
            <Button
              size="sm"
              variant="outline"
              :disabled="isCancelling('sum', r.repository_id)"
              class="shrink-0"
              @click="terminateSummary(r.repository_id, r.name)"
            >
              <span class="icon-[lucide--circle-stop] mr-1 text-destructive" />
              终止
            </Button>
          </div>
        </div>
        <div v-if="summaryOffset > 0 || summaryHasMore" class="flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" :disabled="summaryOffset === 0" @click="summaryPrev">
            上一页
          </Button>
          <Button size="sm" variant="ghost" :disabled="!summaryHasMore" @click="summaryNext">
            下一页
          </Button>
        </div>
      </section>
    </template>
  </div>
</template>
