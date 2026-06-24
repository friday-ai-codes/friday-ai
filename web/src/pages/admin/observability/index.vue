<script setup lang="ts">
import type { ObservabilityResponse } from '~/api/system'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getObservability } from '~/api/system'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'

definePage({
  meta: { requiresAdmin: true },
})

const REFRESH_MS = 4000

const data = ref<ObservabilityResponse | null>(null)
const loading = ref(true)
const error = ref('')
const lastUpdated = ref('')
const autoRefresh = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

async function load(silent = false) {
  if (!silent)
    loading.value = true
  try {
    data.value = await getObservability()
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

function startTimer() {
  stopTimer()
  if (autoRefresh.value)
    timer = setInterval(load, REFRESH_MS, true)
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

// ---- 衍生视图 ----

/** 队列 × 状态 → 透视为 { queue: { status: count } }，并汇总 todo/doing 等。 */
const queuePivot = computed(() => {
  const rows = data.value?.durable_queues.by_queue_status ?? []
  const map: Record<string, Record<string, number>> = {}
  for (const r of rows) {
    map[r.queue] ??= {}
    map[r.queue][r.status] = r.count
  }
  return map
})

const queueTotals = computed(() => data.value?.durable_queues.totals ?? {})

/** subagent 透视 { task_type: { status: count } } */
const subagentPivot = computed(() => {
  const rows = data.value?.subagent.by_type_status ?? []
  const map: Record<string, Record<string, number>> = {}
  for (const r of rows) {
    map[r.task_type] ??= {}
    map[r.task_type][r.status] = r.count
  }
  return map
})

function statusColor(status: string): string {
  if (['running', 'doing', 'indexing'].includes(status))
    return 'text-blue-500 bg-blue-500/10'
  if (['pending', 'todo', 'waiting'].includes(status))
    return 'text-amber-500 bg-amber-500/10'
  if (['completed', 'succeeded', 'indexed'].includes(status))
    return 'text-emerald-500 bg-emerald-500/10'
  if (['failed', 'error', 'timeout', 'cancelled', 'aborted'].includes(status))
    return 'text-rose-500 bg-rose-500/10'
  return 'text-muted-foreground bg-muted'
}

function loadBarColor(pct: number): string {
  if (pct >= 85)
    return 'bg-rose-500'
  if (pct >= 60)
    return 'bg-amber-500'
  return 'bg-emerald-500'
}

function num(v: number | undefined | null): string {
  return v == null ? '-' : (Math.round(v * 10) / 10).toString()
}

function countEntries(obj: Record<string, number> | undefined): [string, number][] {
  return Object.entries(obj ?? {}).sort((a, b) => b[1] - a[1])
}
</script>

<template>
  <div class="max-w-6xl mx-auto space-y-6 p-4 sm:p-6">
    <!-- 标题栏 -->
    <header class="flex flex-wrap items-center gap-3">
      <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
        <span class="icon-[lucide--activity] text-2xl text-primary" />
      </div>
      <div class="flex-1 min-w-0">
        <h1 class="text-2xl font-bold tracking-tight">
          任务与系统总览
        </h1>
        <p class="text-sm text-muted-foreground">
          所有任务队列、状态、进度与各 Runner / 主机负载（仅超级管理员）
        </p>
      </div>
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <span v-if="lastUpdated">更新于 {{ lastUpdated }}</span>
        <Button size="sm" variant="outline" @click="toggleAuto">
          <span :class="autoRefresh ? 'icon-[lucide--pause]' : 'icon-[lucide--play]'" class="w-3.5 h-3.5 mr-1" />
          {{ autoRefresh ? '自动刷新中' : '已暂停' }}
        </Button>
        <Button size="sm" variant="outline" @click="load()">
          <span class="icon-[lucide--refresh-cw] w-3.5 h-3.5 mr-1" />
          刷新
        </Button>
      </div>
    </header>

    <LoadingState v-if="loading && !data" variant="spinner" text="加载总览..." />

    <div v-else-if="error && !data" class="card p-6 text-rose-500 text-sm">
      {{ error }}
    </div>

    <template v-else-if="data">
      <!-- Runner / 主机负载 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--server] w-4 h-4" /> Runner 与主机负载
        </h2>
        <div v-if="data.runners.length === 0" class="card p-4 text-sm text-muted-foreground">
          暂无已注册的 Runner
        </div>
        <div v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="r in data.runners" :key="r.id" class="card p-4 space-y-3">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2 min-w-0">
                <span
                  class="w-2 h-2 rounded-full shrink-0"
                  :class="r.status === 'online' ? 'bg-emerald-500' : 'bg-muted-foreground/40'"
                />
                <span class="font-medium truncate">{{ r.name }}</span>
              </div>
              <span class="text-xs text-muted-foreground">{{ r.version || '—' }}</span>
            </div>
            <div class="flex items-center gap-2 text-xs text-muted-foreground">
              <span class="px-1.5 py-0.5 rounded bg-muted">并发 {{ r.current_tasks }}/{{ r.concurrent }}</span>
              <span :class="r.status === 'online' ? 'text-emerald-500' : 'text-muted-foreground'">{{ r.status }}</span>
            </div>
            <!-- 负载条 -->
            <div class="space-y-2">
              <div v-for="metric in ([['CPU', r.load.cpu_percent], ['内存', r.load.mem_percent], ['磁盘', r.load.disk_percent]] as [string, number | undefined][])" :key="metric[0]" class="space-y-0.5">
                <div class="flex justify-between text-[11px] text-muted-foreground">
                  <span>{{ metric[0] }}</span>
                  <span>{{ num(metric[1]) }}%</span>
                </div>
                <div class="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    :class="loadBarColor(metric[1] ?? 0)"
                    :style="{ width: `${Math.min(100, metric[1] ?? 0)}%` }"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- durable 队列（索引/图谱等） -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--layers] w-4 h-4" /> 持久化队列（索引 / 图谱 / 页面 / 维护）
        </h2>
        <div class="card p-4 space-y-4">
          <!-- 汇总 chips -->
          <div class="flex flex-wrap gap-2">
            <span v-if="countEntries(queueTotals).length === 0" class="text-sm text-muted-foreground">队列为空</span>
            <span
              v-for="[status, count] in countEntries(queueTotals)"
              :key="status"
              class="px-2.5 py-1 rounded-lg text-xs font-medium"
              :class="statusColor(status)"
            >
              {{ status }} · {{ count }}
            </span>
          </div>
          <!-- 每队列明细 -->
          <div class="space-y-2">
            <div
              v-for="(statuses, queue) in queuePivot"
              :key="queue"
              class="flex items-center gap-3 text-sm"
            >
              <span class="w-28 shrink-0 font-mono text-xs text-muted-foreground">{{ queue }}</span>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="(count, status) in statuses"
                  :key="status"
                  class="px-2 py-0.5 rounded text-xs"
                  :class="statusColor(status)"
                >
                  {{ status }}:{{ count }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- SubAgent 任务（summary / coding / explore） -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--bot] w-4 h-4" /> 容器任务（AI 描述 / 编码 / 探索）
        </h2>
        <div class="card p-4 space-y-4">
          <div class="space-y-2">
            <div
              v-for="(statuses, type) in subagentPivot"
              :key="type"
              class="flex items-center gap-3 text-sm"
            >
              <span class="w-28 shrink-0 font-mono text-xs text-muted-foreground">{{ type }}</span>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="(count, status) in statuses"
                  :key="status"
                  class="px-2 py-0.5 rounded text-xs"
                  :class="statusColor(status)"
                >
                  {{ status }}:{{ count }}
                </span>
              </div>
            </div>
          </div>
          <!-- 活跃任务列表 -->
          <div v-if="data.subagent.active.length" class="border-t border-border/50 pt-3">
            <div class="text-xs text-muted-foreground mb-2">
              活跃任务（{{ data.subagent.active.length }}）
            </div>
            <div class="max-h-64 overflow-y-auto space-y-1">
              <div
                v-for="item in data.subagent.active"
                :key="item.session_id"
                class="flex items-center gap-2 text-xs py-1 border-b border-border/30 last:border-0"
              >
                <span class="px-1.5 py-0.5 rounded shrink-0" :class="statusColor(item.status)">{{ item.status }}</span>
                <span class="font-mono text-muted-foreground shrink-0">{{ item.task_type }}</span>
                <span class="truncate text-muted-foreground/70">{{ item.repository_id || item.session_id }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 仓库状态 + 对话编排 -->
      <section class="grid gap-3 lg:grid-cols-2">
        <div class="card p-4 space-y-3">
          <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
            <span class="icon-[lucide--database] w-4 h-4" /> 仓库（共 {{ data.repositories.total }}）
          </h2>
          <div class="space-y-2">
            <div v-for="dim in ([['索引', data.repositories.index_status], ['图谱', data.repositories.graph_status], ['AI 描述', data.repositories.ai_summary_status]] as [string, Record<string, number>][])" :key="dim[0]" class="flex items-center gap-3">
              <span class="w-16 shrink-0 text-xs text-muted-foreground">{{ dim[0] }}</span>
              <div class="flex flex-wrap gap-1.5">
                <span v-if="countEntries(dim[1]).length === 0" class="text-xs text-muted-foreground/60">—</span>
                <span
                  v-for="[status, count] in countEntries(dim[1])"
                  :key="status"
                  class="px-2 py-0.5 rounded text-xs"
                  :class="statusColor(status)"
                >
                  {{ status }}:{{ count }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="card p-4 space-y-3">
          <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
            <span class="icon-[lucide--messages-square] w-4 h-4" /> 对话编排
          </h2>
          <div class="flex flex-wrap gap-2">
            <span v-if="countEntries(data.orchestration).length === 0" class="text-xs text-muted-foreground/60">暂无</span>
            <span
              v-for="[status, count] in countEntries(data.orchestration)"
              :key="status"
              class="px-2.5 py-1 rounded-lg text-xs font-medium"
              :class="statusColor(status)"
            >
              {{ status }} · {{ count }}
            </span>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
