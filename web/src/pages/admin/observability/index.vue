<script setup lang="ts">
import type { ObservabilityResponse, ServiceHealth, SystemHealth, SystemLogEntry } from '~/api/system'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getObservability, getSystemHealth, getSystemLogs } from '~/api/system'
import {
  axisLabelStyle,
  axisLineStyle,
  chartGrid,
  legendTextStyle,
  splitLineStyle,
  tooltipStyle,
} from '~/components/analytics/chart-theme'
import { VChart } from '~/components/analytics/echarts-setup'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'

definePage({
  meta: { requiresAdmin: true },
})

const REFRESH_MS = 4000
// 客户端滚动缓冲上限：60 个采样点 ≈ 4s × 60 = 4 分钟实时窗口（无后端时序，纯实时采样）。
const MAX_SAMPLES = 60
const LOG_LIMIT = 200

const data = ref<ObservabilityResponse | null>(null)
const health = ref<SystemHealth | null>(null)
const logs = ref<SystemLogEntry[]>([])
const logLevel = ref<string>('')
const loading = ref(true)
const error = ref('')
const lastUpdated = ref('')
const autoRefresh = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

interface Sample {
  t: string
  active: number
  pending: number
  coroutines: number
  threads: number
}
const samples = ref<Sample[]>([])

async function load(silent = false) {
  if (!silent)
    loading.value = true
  try {
    const [obs, hp, lg] = await Promise.all([
      getObservability(),
      getSystemHealth().catch(() => null),
      getSystemLogs({ limit: LOG_LIMIT, level: logLevel.value || undefined }).catch(() => ({ logs: [] })),
    ])
    data.value = obs
    if (hp)
      health.value = hp
    logs.value = lg.logs
    error.value = ''
    lastUpdated.value = new Date().toLocaleTimeString()
    pushSample(obs)
  }
  catch (e: any) {
    error.value = e?.detail || e?.message || '加载失败'
  }
  finally {
    loading.value = false
  }
}

function pushSample(obs: ObservabilityResponse) {
  const totals = obs.durable_queues.totals ?? {}
  const pending = (totals.todo ?? 0) + (totals.doing ?? 0)
  samples.value.push({
    t: new Date().toLocaleTimeString(),
    active: obs.subagent.active.length,
    pending,
    coroutines: obs.runtime?.asyncio_tasks ?? 0,
    threads: obs.runtime?.threads ?? 0,
  })
  if (samples.value.length > MAX_SAMPLES)
    samples.value.shift()
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
function setLogLevel(level: string) {
  logLevel.value = level
  load(true)
}

onMounted(() => {
  load()
  startTimer()
})
onUnmounted(stopTimer)

// ---- 衍生视图 ----

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

const subagentPivot = computed(() => {
  const rows = data.value?.subagent.by_type_status ?? []
  const map: Record<string, Record<string, number>> = {}
  for (const r of rows) {
    map[r.task_type] ??= {}
    map[r.task_type][r.status] = r.count
  }
  return map
})

// 顶部汇总数字
const onlineRunners = computed(() => data.value?.runners.filter(r => r.status === 'online').length ?? 0)
const totalRunners = computed(() => data.value?.runners.length ?? 0)
const activeTasks = computed(() => data.value?.subagent.active.length ?? 0)
const repoTotal = computed(() => data.value?.repositories.total ?? 0)
const runtime = computed(() => data.value?.runtime)
const bg = computed(() => data.value?.background_tasks)
const alerts = computed(() => data.value?.alerts)

// 服务健康
const overallHealthy = computed(() => health.value?.overall === 'healthy')
const services = computed<ServiceHealth[]>(() => health.value?.services ?? [])

function healthClasses(status: string): string {
  if (status === 'healthy')
    return 'text-emerald-500 bg-emerald-500/10'
  if (status === 'unhealthy')
    return 'text-rose-500 bg-rose-500/10'
  return 'text-muted-foreground bg-muted'
}
function healthLabel(status: string): string {
  if (status === 'healthy')
    return '正常'
  if (status === 'unhealthy')
    return '异常'
  return '未配置'
}

function statusColor(status: string): string {
  if (['running', 'doing', 'indexing'].includes(status))
    return 'text-blue-500 bg-blue-500/10'
  if (['pending', 'todo', 'waiting'].includes(status))
    return 'text-amber-500 bg-amber-500/10'
  if (['completed', 'succeeded', 'indexed', 'delivered'].includes(status))
    return 'text-emerald-500 bg-emerald-500/10'
  if (['failed', 'error', 'timeout', 'cancelled', 'aborted', 'triggered'].includes(status))
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

// ---- 日志级别样式 ----
const LOG_LEVELS = ['', 'INFO', 'WARNING', 'ERROR']
function logLevelLabel(l: string): string {
  return l === '' ? '全部' : l
}
function logLevelClass(level: string): string {
  const u = (level || '').toUpperCase()
  if (u === 'ERROR' || u === 'CRITICAL' || u === 'FATAL')
    return 'text-rose-500 bg-rose-500/10'
  if (u === 'WARNING' || u === 'WARN')
    return 'text-amber-500 bg-amber-500/10'
  if (u === 'DEBUG')
    return 'text-muted-foreground bg-muted'
  return 'text-blue-500 bg-blue-500/10'
}
function fmtLogTime(ts: string | null): string {
  if (!ts)
    return '--:--:--'
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts.slice(11, 19) : d.toLocaleTimeString()
}
function fmtAlertTime(ts: string): string {
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString()
}
function conditionLabel(t: string): string {
  const map: Record<string, string> = {
    execution_failed: '执行失败',
    execution_timeout: '执行超时',
    cost_threshold: '成本超阈值',
    node_error_code: '节点错误码',
  }
  return map[t] || t || '—'
}

// ---- 实时趋势图（客户端滚动采样，非后端时序）----
function lineSeries(name: string, color: string, key: keyof Sample) {
  return {
    name,
    type: 'line' as const,
    smooth: true,
    showSymbol: false,
    areaStyle: {
      color: {
        type: 'linear' as const,
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: `${color}40` },
          { offset: 1, color: `${color}05` },
        ],
      },
    },
    lineStyle: { color, width: 2.5 },
    itemStyle: { color },
    data: samples.value.map(p => p[key]),
  }
}

function baseOption(legend: string[]) {
  return {
    tooltip: { trigger: 'axis' as const, ...tooltipStyle },
    legend: { data: legend, textStyle: legendTextStyle, icon: 'circle', itemWidth: 8, itemHeight: 8 },
    grid: chartGrid,
    xAxis: {
      type: 'category' as const,
      data: samples.value.map(p => p.t),
      boundaryGap: false,
      axisLine: axisLineStyle,
      axisLabel: axisLabelStyle,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      minInterval: 1,
      axisLine: { show: false },
      axisLabel: axisLabelStyle,
      splitLine: splitLineStyle,
    },
  }
}

const taskTrendOption = computed(() => ({
  ...baseOption(['活跃容器任务', '队列待处理']),
  series: [
    lineSeries('活跃容器任务', '#3b82f6', 'active'),
    lineSeries('队列待处理', '#f59e0b', 'pending'),
  ],
}))

const runtimeTrendOption = computed(() => ({
  ...baseOption(['协程数', '线程数']),
  series: [
    lineSeries('协程数', '#8b5cf6', 'coroutines'),
    lineSeries('线程数', '#10b981', 'threads'),
  ],
}))
</script>

<template>
  <div class="max-w-7xl mx-auto space-y-6 p-4 sm:p-6">
    <!-- 标题栏 -->
    <header class="flex flex-wrap items-center gap-3">
      <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
        <span class="icon-[lucide--activity] text-2xl text-primary" />
      </div>
      <div class="flex-1 min-w-0">
        <h1 class="text-2xl font-bold tracking-tight">
          运维监控
        </h1>
        <p class="text-sm text-muted-foreground">
          协程与后台任务、服务健康、告警事件与系统日志（仅超级管理员）
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

    <LoadingState v-if="loading && !data" variant="spinner" text="加载监控数据..." />

    <div v-else-if="error && !data" class="card p-6 text-rose-500 text-sm">
      {{ error }}
    </div>

    <template v-else-if="data">
      <!-- 顶部关键指标卡 -->
      <section class="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
        <div class="card p-4 space-y-1">
          <div class="flex items-center gap-2 text-xs text-muted-foreground">
            <span class="w-2 h-2 rounded-full" :class="overallHealthy ? 'bg-emerald-500' : 'bg-rose-500'" />
            整体状态
          </div>
          <div class="text-2xl font-bold tabular-nums" :class="overallHealthy ? 'text-emerald-500' : 'text-rose-500'">
            {{ overallHealthy ? '正常' : '异常' }}
          </div>
        </div>
        <div class="card p-4 space-y-1">
          <div class="text-xs text-muted-foreground flex items-center gap-1">
            <span class="icon-[lucide--git-branch] w-3.5 h-3.5" /> 协程数
          </div>
          <div class="text-2xl font-bold tabular-nums text-violet-500">
            {{ runtime?.asyncio_tasks ?? '-' }}
          </div>
          <div class="text-[11px] text-muted-foreground">
            线程 {{ runtime?.threads ?? '-' }}
          </div>
        </div>
        <div class="card p-4 space-y-1">
          <div class="text-xs text-muted-foreground flex items-center gap-1">
            <span class="icon-[lucide--layers] w-3.5 h-3.5" /> 后台任务
          </div>
          <div class="text-2xl font-bold tabular-nums text-amber-500">
            {{ bg?.total_active ?? 0 }}
          </div>
          <div class="text-[11px] text-muted-foreground">
            队列 {{ bg?.durable_active ?? 0 }} · 容器 {{ bg?.subagent_active ?? 0 }}
          </div>
        </div>
        <div class="card p-4 space-y-1">
          <div class="text-xs text-muted-foreground flex items-center gap-1">
            <span class="icon-[lucide--bot] w-3.5 h-3.5" /> 活跃容器任务
          </div>
          <div class="text-2xl font-bold tabular-nums text-blue-500">
            {{ activeTasks }}
          </div>
        </div>
        <div class="card p-4 space-y-1">
          <div class="text-xs text-muted-foreground flex items-center gap-1">
            <span class="icon-[lucide--server] w-3.5 h-3.5" /> 在线 Runner
          </div>
          <div class="text-2xl font-bold tabular-nums">
            {{ onlineRunners }}<span class="text-sm text-muted-foreground font-normal">/{{ totalRunners }}</span>
          </div>
        </div>
        <div class="card p-4 space-y-1">
          <div class="text-xs text-muted-foreground flex items-center gap-1">
            <span class="icon-[lucide--database] w-3.5 h-3.5" /> 仓库总数
          </div>
          <div class="text-2xl font-bold tabular-nums">
            {{ repoTotal }}
          </div>
        </div>
      </section>

      <!-- 服务健康 -->
      <section class="space-y-3">
        <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <span class="icon-[lucide--heart-pulse] w-4 h-4" /> 服务健康
        </h2>
        <div v-if="services.length === 0" class="card p-4 text-sm text-muted-foreground">
          暂无健康检查数据
        </div>
        <div v-else class="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
          <div v-for="svc in services" :key="svc.name" class="card p-4 space-y-2">
            <div class="flex items-center justify-between">
              <span class="font-medium text-sm">{{ svc.label }}</span>
              <span class="px-2 py-0.5 rounded text-xs font-medium" :class="healthClasses(svc.status)">
                {{ healthLabel(svc.status) }}
              </span>
            </div>
            <div class="flex items-center justify-between text-[11px] text-muted-foreground">
              <span class="truncate">{{ svc.message || '—' }}</span>
              <span v-if="svc.latency_ms != null" class="shrink-0 tabular-nums">{{ num(svc.latency_ms) }}ms</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 实时趋势：任务 + 运行时（协程/线程） -->
      <section class="grid gap-3 lg:grid-cols-2">
        <div class="card p-4 space-y-3">
          <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
            <span class="icon-[lucide--trending-up] w-4 h-4" /> 任务趋势
            <span class="text-[11px] font-normal text-muted-foreground/60">（每 {{ REFRESH_MS / 1000 }}s 采样）</span>
          </h2>
          <div v-if="samples.length < 2" class="h-[240px] flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <span class="icon-[lucide--line-chart] text-3xl opacity-30" />
            <span class="text-sm">采样中，请稍候...</span>
          </div>
          <VChart v-else :option="taskTrendOption" style="height: 240px" autoresize />
        </div>
        <div class="card p-4 space-y-3">
          <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
            <span class="icon-[lucide--cpu] w-4 h-4" /> 运行时趋势（协程 / 线程）
          </h2>
          <div v-if="samples.length < 2" class="h-[240px] flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <span class="icon-[lucide--line-chart] text-3xl opacity-30" />
            <span class="text-sm">采样中，请稍候...</span>
          </div>
          <VChart v-else :option="runtimeTrendOption" style="height: 240px" autoresize />
        </div>
      </section>

      <!-- 告警事件 + 持久化队列 -->
      <section class="grid gap-3 lg:grid-cols-2">
        <div class="card p-4 space-y-3">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
              <span class="icon-[lucide--bell-ring] w-4 h-4" /> 告警事件
            </h2>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="[status, count] in countEntries(alerts?.counts)"
                :key="status"
                class="px-2 py-0.5 rounded text-xs font-medium"
                :class="statusColor(status)"
              >
                {{ status }}:{{ count }}
              </span>
            </div>
          </div>
          <div v-if="!alerts?.recent?.length" class="h-40 flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <span class="icon-[lucide--bell-off] text-3xl opacity-30" />
            <span class="text-sm">暂无告警事件</span>
          </div>
          <div v-else class="max-h-72 overflow-y-auto -mx-1 px-1 space-y-2">
            <div
              v-for="a in alerts.recent"
              :key="a.id"
              class="flex items-start gap-3 rounded-lg border border-border/40 bg-muted/20 p-2.5"
            >
              <span class="mt-0.5 px-1.5 py-0.5 rounded text-[11px] font-medium shrink-0" :class="statusColor(a.status)">
                {{ a.status }}
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2">
                  <span class="font-medium text-sm truncate">{{ a.rule_name || '未命名规则' }}</span>
                  <span class="text-[11px] text-muted-foreground shrink-0 tabular-nums">{{ fmtAlertTime(a.triggered_at) }}</span>
                </div>
                <div class="text-xs text-muted-foreground">
                  {{ conditionLabel(a.condition_type) }}
                  <template v-if="a.error_message">
                    · <span class="text-rose-500/80">{{ a.error_message }}</span>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="card p-4 space-y-4">
          <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
            <span class="icon-[lucide--layers] w-4 h-4" /> 持久化队列（索引 / 图谱 / 页面 / 维护）
          </h2>
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
                  class="px-2 py-0.5 rounded text-xs tabular-nums"
                  :class="statusColor(status)"
                >
                  {{ status }}:{{ count }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 系统日志 -->
      <section class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-semibold text-muted-foreground flex items-center gap-2">
            <span class="icon-[lucide--scroll-text] w-4 h-4" /> 系统日志
            <span class="text-[11px] font-normal text-muted-foreground/60">（内存最近 {{ LOG_LIMIT }} 条，每进程）</span>
          </h2>
          <div class="flex items-center gap-1">
            <button
              v-for="lv in LOG_LEVELS"
              :key="lv || 'all'"
              type="button"
              class="px-2.5 py-1 rounded-md text-xs font-medium transition-colors"
              :class="logLevel === lv ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-muted/70'"
              @click="setLogLevel(lv)"
            >
              {{ logLevelLabel(lv) }}
            </button>
          </div>
        </div>
        <div class="card overflow-hidden">
          <div v-if="!logs.length" class="h-40 flex flex-col items-center justify-center gap-2 text-muted-foreground">
            <span class="icon-[lucide--file-search] text-3xl opacity-30" />
            <span class="text-sm">暂无日志</span>
          </div>
          <div v-else class="max-h-112 overflow-y-auto divide-y divide-border/30 font-mono text-xs">
            <div
              v-for="(log, i) in logs"
              :key="i"
              class="flex items-start gap-3 px-3 py-1.5 hover:bg-muted/30"
            >
              <span class="shrink-0 text-muted-foreground/70 tabular-nums">{{ fmtLogTime(log.ts) }}</span>
              <span class="shrink-0 w-16 text-center px-1 rounded font-sans text-[10px] font-semibold" :class="logLevelClass(log.level)">
                {{ log.level }}
              </span>
              <span class="shrink-0 max-w-40 truncate text-muted-foreground/80" :title="log.logger">{{ log.logger || '—' }}</span>
              <span class="min-w-0 flex-1 break-all text-foreground/90">{{ log.message }}</span>
            </div>
          </div>
        </div>
      </section>

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
              <span class="px-1.5 py-0.5 rounded bg-muted tabular-nums">并发 {{ r.current_tasks }}/{{ r.concurrent }}</span>
              <span :class="r.status === 'online' ? 'text-emerald-500' : 'text-muted-foreground'">{{ r.status }}</span>
            </div>
            <div class="space-y-2">
              <div v-for="metric in ([['CPU', r.load.cpu_percent], ['内存', r.load.mem_percent], ['磁盘', r.load.disk_percent]] as [string, number | undefined][])" :key="metric[0]" class="space-y-0.5">
                <div class="flex justify-between text-[11px] text-muted-foreground">
                  <span>{{ metric[0] }}</span>
                  <span class="tabular-nums">{{ num(metric[1]) }}%</span>
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

      <!-- 容器任务 -->
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
                  class="px-2 py-0.5 rounded text-xs tabular-nums"
                  :class="statusColor(status)"
                >
                  {{ status }}:{{ count }}
                </span>
              </div>
            </div>
          </div>
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
                  class="px-2 py-0.5 rounded text-xs tabular-nums"
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
              class="px-2.5 py-1 rounded-lg text-xs font-medium tabular-nums"
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
