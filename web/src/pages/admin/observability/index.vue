<script setup lang="ts">
/**
 * 运维大盘总览页（UI-01 + UI-02）。
 *
 * 后端时序驱动 + 保留自动刷新：顶部统一三视图 tab 导航 + 时间范围选择器（5m/1h/24h/
 * 自定义）+ 自动刷新开关；消费 75-01 封装的 getMetricsSnapshot / queryMetrics / querySla，
 * 组合复合健康分圆环、实时速率卡、6 张信息卡、内联阈值快照行、4 类趋势图。
 *
 * 自动刷新：开启时按固定间隔 invalidate 全部 `obs-*` query（趋势/卡片随之重拉）+ 重拉
 * 快照；页面隐藏（visibilitychange）时暂停，onUnmounted 清理（观测代码不反噬业务，
 * 拉数全部 best-effort，单源失败不崩页）。
 *
 * 口径取舍：metrics_query agg 白名单含 p99/p95/p90/p50/avg/max，故请求时长 / TTFT 大字头
 * 取 **P99**（per UI-SPEC §2.3），P95/P90/P50/Avg/Max 列于副行；上游错误 429/529/其它上游码
 * 由 metrics_query 'upstream' 维度（ModelUsageRecord.upstream_status_code）单列驱动。
 */
import type { MetricPoint, MetricsQueryResult, SlaPoint } from '~/api/system'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getMetricsSnapshot, queryMetrics, querySla } from '~/api/system'
import {
  EMPTY,
  formatDurationMs,
  formatNumber,
} from '~/components/observability/format'
import HealthScoreGauge from '~/components/observability/HealthScoreGauge.vue'
import MetricInfoCard from '~/components/observability/MetricInfoCard.vue'
import ObservabilityTabs from '~/components/observability/ObservabilityTabs.vue'
import ObservabilityTimeRange from '~/components/observability/ObservabilityTimeRange.vue'
import RealtimeRateCard from '~/components/observability/RealtimeRateCard.vue'
import SnapshotRow from '~/components/observability/SnapshotRow.vue'
import TrendCharts from '~/components/observability/TrendCharts.vue'

definePage({
  meta: { requiresAdmin: true },
})

// ── 时间范围 + 自动刷新 ────────────────────────────────────────────────
const timeRange = ref<{ start: string, end: string }>({
  start: new Date(Date.now() - 60 * 60_000).toISOString(),
  end: new Date().toISOString(),
})
const autoRefresh = ref(true)
const AUTO_REFRESH_MS = 5000

const queryClient = useQueryClient()
let timer: ReturnType<typeof setInterval> | null = null

function refreshAll() {
  queryClient.invalidateQueries({
    predicate: q => typeof q.queryKey[0] === 'string' && (q.queryKey[0] as string).startsWith('obs-'),
  })
}

function startTimer() {
  stopTimer()
  if (autoRefresh.value) {
    timer = setInterval(() => {
      if (!document.hidden)
        refreshAll()
    }, AUTO_REFRESH_MS)
  }
}
function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function onAutoRefreshChange(v: boolean) {
  autoRefresh.value = v
  startTimer()
}

onMounted(startTimer)
onUnmounted(stopTimer)

// ── 数据拉取（全部 best-effort，单源失败回退空） ──────────────────────────
const { data: snapshot, isLoading: snapshotLoading } = useQuery({
  queryKey: ['obs-snapshot'],
  queryFn: () => getMetricsSnapshot(),
  placeholderData: keepPreviousData,
  refetchInterval: () => (autoRefresh.value ? AUTO_REFRESH_MS : false),
  retry: 1,
})

function rangeKey() {
  return timeRange.value
}

const { data: qpsTotal } = useQuery({
  queryKey: ['obs-qps-total', rangeKey],
  queryFn: () => queryMetrics({ metric: 'qps', dimension: '', start: timeRange.value.start, end: timeRange.value.end }),
  placeholderData: keepPreviousData,
})
const { data: tpsTotal } = useQuery({
  queryKey: ['obs-tps-total', rangeKey],
  queryFn: () => queryMetrics({ metric: 'tps', dimension: '', start: timeRange.value.start, end: timeRange.value.end }),
  placeholderData: keepPreviousData,
})
const { data: errorBreakdown } = useQuery({
  queryKey: ['obs-error-breakdown', rangeKey],
  queryFn: () => queryMetrics({ metric: 'error', dimension: 'error_class', start: timeRange.value.start, end: timeRange.value.end }),
  placeholderData: keepPreviousData,
})
const { data: slaData } = useQuery({
  queryKey: ['obs-sla', rangeKey],
  queryFn: () => querySla({ start: timeRange.value.start, end: timeRange.value.end }),
  placeholderData: keepPreviousData,
})
// 上游错误码分布（429/529/other）：ModelUsageRecord.upstream_status_code 聚合。
const { data: upstreamBreakdown } = useQuery({
  queryKey: ['obs-upstream-breakdown', rangeKey],
  queryFn: () => queryMetrics({ metric: 'upstream', dimension: '', start: timeRange.value.start, end: timeRange.value.end }),
  placeholderData: keepPreviousData,
})

const DURATION_AGGS = ['p99', 'p95', 'p90', 'p50', 'avg', 'max'] as const
function usePercentileQuery(key: string, metric: 'duration' | 'ttft') {
  return useQuery({
    queryKey: [key, rangeKey],
    queryFn: async () => {
      const results = await Promise.all(
        DURATION_AGGS.map(agg => queryMetrics({ metric, agg, dimension: '', start: timeRange.value.start, end: timeRange.value.end })),
      )
      return Object.fromEntries(DURATION_AGGS.map((agg, i) => [agg, results[i]])) as Record<typeof DURATION_AGGS[number], MetricsQueryResult<MetricPoint>>
    },
    placeholderData: keepPreviousData,
  })
}
const { data: durationData } = usePercentileQuery('obs-duration', 'duration')
const { data: ttftData } = usePercentileQuery('obs-ttft', 'ttft')

// ── 派生口径 ──────────────────────────────────────────────────────────
function sumSeries(result: MetricsQueryResult<MetricPoint> | undefined): number {
  if (!result?.series?.length)
    return 0
  return result.series.reduce((s, p) => s + (p.value ?? 0), 0)
}

/** 窗口秒数（用于把累计请求/token 换算平均速率）。 */
const windowSeconds = computed(() => {
  const s = new Date(timeRange.value.start).getTime()
  const e = new Date(timeRange.value.end).getTime()
  return Math.max(1, (e - s) / 1000)
})

const totalRequests = computed(() => sumSeries(qpsTotal.value))
const totalTokens = computed(() => sumSeries(tpsTotal.value))
const avgQps = computed(() => totalRequests.value / windowSeconds.value)
const avgTps = computed(() => totalTokens.value / windowSeconds.value)

/** 错误分解：按 error_class 维度汇总 system/upstream/business。 */
const errorCounts = computed(() => {
  const out = { system: 0, upstream: 0, business: 0 }
  for (const p of errorBreakdown.value?.series ?? []) {
    const k = p.dim as keyof typeof out
    if (k in out)
      out[k] += p.value ?? 0
  }
  return out
})

// 请求错误率（排除业务限制，与 SLA 口径一致）+ 上游错误率，喂健康分。
const errorRate = computed(() => {
  const req = totalRequests.value
  if (req <= 0)
    return null
  return (errorCounts.value.system + errorCounts.value.upstream) / req
})
const upstreamErrorRate = computed(() => {
  const req = totalRequests.value
  if (req <= 0)
    return null
  return errorCounts.value.upstream / req
})

/** 上游错误码分布：按 dim(429/529/other) 汇总 ModelUsageRecord 上游码计数。 */
const upstreamCounts = computed(() => {
  const out = { c429: 0, c529: 0, other: 0 }
  for (const p of upstreamBreakdown.value?.series ?? []) {
    if (p.dim === '429')
      out.c429 += p.value ?? 0
    else if (p.dim === '529')
      out.c529 += p.value ?? 0
    else
      out.other += p.value ?? 0
  }
  return out
})

/** SLA 汇总：(Σeligible - Σfailures)/Σeligible。 */
const slaSummary = computed(() => {
  const series: SlaPoint[] = slaData.value?.series ?? []
  let eligible = 0
  let failures = 0
  let businessRejected = 0
  for (const p of series) {
    eligible += p.eligible ?? 0
    failures += p.failures ?? 0
    businessRejected += p.business_rejected ?? 0
  }
  const availability = eligible > 0 ? (eligible - failures) / eligible : null
  return { availability, failures, businessRejected, eligible }
})

/** 分位汇总：对 series 取均值；max agg 取最大值（窗口概览口径）。 */
function summarizeAgg(result: MetricsQueryResult<MetricPoint> | undefined, mode: 'mean' | 'max'): number | null {
  const vals = (result?.series ?? []).map(p => p.value).filter((v): v is number => v != null)
  if (!vals.length)
    return null
  if (mode === 'max')
    return Math.max(...vals)
  return vals.reduce((s, v) => s + v, 0) / vals.length
}

function percentileSummary(data: Record<typeof DURATION_AGGS[number], MetricsQueryResult<MetricPoint>> | undefined) {
  return {
    p99: summarizeAgg(data?.p99, 'mean'),
    p95: summarizeAgg(data?.p95, 'mean'),
    p90: summarizeAgg(data?.p90, 'mean'),
    p50: summarizeAgg(data?.p50, 'mean'),
    avg: summarizeAgg(data?.avg, 'mean'),
    max: summarizeAgg(data?.max, 'max'),
  }
}
const durationStats = computed(() => percentileSummary(durationData.value))
const ttftStats = computed(() => percentileSummary(ttftData.value))

// ── 6 信息卡组装 ──────────────────────────────────────────────────────
const slaTone = computed<'success' | 'warning' | 'danger' | 'default'>(() => {
  const a = slaSummary.value.availability
  if (a == null)
    return 'default'
  if (a >= 0.99)
    return 'success'
  if (a >= 0.95)
    return 'warning'
  return 'danger'
})

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v))
    return EMPTY
  return `${(v * 100).toFixed(digits)}%`
}
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
    <!-- 标题栏 -->
    <header class="flex flex-wrap items-center gap-3">
      <div class="flex items-center justify-center rounded-xl bg-primary/10 p-2.5">
        <span class="icon-[lucide--layout-dashboard] text-2xl text-primary" />
      </div>
      <div class="min-w-0 flex-1">
        <h1 class="text-2xl font-bold tracking-tight">
          运维大盘
        </h1>
        <p class="text-sm text-muted-foreground">
          整体健康、实时速率与关键口径（仅超级管理员）
        </p>
      </div>
    </header>

    <!-- 三视图导航 + 时间范围 + 自动刷新 -->
    <div class="space-y-3">
      <ObservabilityTabs />
      <ObservabilityTimeRange
        v-model="timeRange"
        :auto-refresh="autoRefresh"
        @update:auto-refresh="onAutoRefreshChange"
        @refresh="refreshAll"
      />
    </div>

    <!-- 第一行：健康分 + 实时速率 -->
    <section class="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr]">
      <HealthScoreGauge
        :snapshot="snapshot ?? null"
        :error-rate="errorRate"
        :upstream-error-rate="upstreamErrorRate"
        :loading="snapshotLoading && !snapshot"
      />
      <RealtimeRateCard />
    </section>

    <!-- 第二行：6 张信息卡 -->
    <section class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <!-- 请求汇总 -->
      <MetricInfoCard
        title="请求汇总"
        icon="lucide--inbox"
        icon-class="bg-blue-500/10 text-blue-600"
        :main-value="formatNumber(totalRequests)"
        main-label="请求数"
        :sub-items="[
          { label: 'Token 数', value: formatNumber(totalTokens) },
          { label: '平均 QPS', value: formatNumber(avgQps, 2) },
          { label: '平均 TPS', value: formatNumber(avgTps, 2) },
        ]"
      />

      <!-- SLA -->
      <MetricInfoCard
        title="SLA 可用率"
        icon="lucide--shield-check"
        icon-class="bg-emerald-500/10 text-emerald-600"
        :main-value="fmtPct(slaSummary.availability)"
        main-label="可用率"
        :tone="slaTone"
        :sub-items="[
          { label: '异常数', value: formatNumber(slaSummary.failures) },
          { label: '有效请求', value: formatNumber(slaSummary.eligible) },
        ]"
        footnote="排除业务限制（含系统繁忙限流）"
      />

      <!-- 请求错误 -->
      <MetricInfoCard
        title="请求错误"
        icon="lucide--circle-alert"
        icon-class="bg-rose-500/10 text-rose-600"
        :main-value="fmtPct(errorRate)"
        main-label="错误率"
        :tone="errorRate != null && errorRate >= 0.05 ? 'danger' : errorRate != null && errorRate >= 0.01 ? 'warning' : 'default'"
        :sub-items="[
          { label: '系统错误', value: formatNumber(errorCounts.system) },
          { label: '业务限制', value: formatNumber(errorCounts.business) },
        ]"
        footnote="错误率排除业务限制（与 SLA 口径一致）"
      />

      <!-- 请求时长 -->
      <MetricInfoCard
        title="请求时长"
        icon="lucide--timer"
        icon-class="bg-amber-500/10 text-amber-600"
        :main-value="formatDurationMs(durationStats.p99)"
        main-label="P99"
        :sub-items="[
          { label: 'P95', value: formatDurationMs(durationStats.p95) },
          { label: 'P90', value: formatDurationMs(durationStats.p90) },
          { label: 'P50', value: formatDurationMs(durationStats.p50) },
          { label: 'Avg', value: formatDurationMs(durationStats.avg) },
          { label: 'Max', value: formatDurationMs(durationStats.max) },
        ]"
        footnote="头部为 P99（Postgres percentile_cont；SQLite 近似降级）"
      />

      <!-- TTFT -->
      <MetricInfoCard
        title="首字延迟 TTFT"
        icon="lucide--gauge"
        icon-class="bg-violet-500/10 text-violet-600"
        :main-value="formatDurationMs(ttftStats.p99)"
        main-label="P99"
        :sub-items="[
          { label: 'P95', value: formatDurationMs(ttftStats.p95) },
          { label: 'P90', value: formatDurationMs(ttftStats.p90) },
          { label: 'P50', value: formatDurationMs(ttftStats.p50) },
          { label: 'Avg', value: formatDurationMs(ttftStats.avg) },
          { label: 'Max', value: formatDurationMs(ttftStats.max) },
        ]"
        footnote="头部为 P99（Postgres percentile_cont；SQLite 近似降级）"
      />

      <!-- 上游错误 -->
      <MetricInfoCard
        title="上游错误"
        icon="lucide--cloud-alert"
        icon-class="bg-orange-500/10 text-orange-600"
        :main-value="fmtPct(upstreamErrorRate)"
        main-label="上游错误率"
        :tone="upstreamErrorRate != null && upstreamErrorRate >= 0.05 ? 'danger' : 'default'"
        :sub-items="[
          { label: '429 限流', value: formatNumber(upstreamCounts.c429) },
          { label: '529 过载', value: formatNumber(upstreamCounts.c529) },
          { label: '其它上游码', value: formatNumber(upstreamCounts.other) },
          { label: '上游错误数', value: formatNumber(errorCounts.upstream) },
        ]"
        footnote="429 / 529 来自模型调用上游状态码（ModelUsageRecord）"
      />
    </section>

    <!-- 第三行：快照行 -->
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        <span class="icon-[lucide--server] h-4 w-4" /> 当前快照
      </h2>
      <SnapshotRow :snapshot="snapshot ?? null" :loading="snapshotLoading && !snapshot" />
    </section>

    <!-- 第四行：趋势 -->
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        <span class="icon-[lucide--trending-up] h-4 w-4" /> 时序趋势
      </h2>
      <TrendCharts :time-range="timeRange" />
    </section>
  </div>
</template>
