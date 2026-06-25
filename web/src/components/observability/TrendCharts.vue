<script setup lang="ts">
/**
 * 趋势区（UI-SPEC §3.2）：4 类后端时序趋势图，统一 ChartCard 外壳 + VChart 出图。
 *
 *   1. 吞吐趋势：各维度 QPS（折线）+ 总 TPS（千，副轴）；维度可切 provider / call_source。
 *   2. 错误趋势：error by error_class → 系统 / 上游 / 业务限制 三线（缺失补 0）。
 *   3. 请求时长趋势：duration p95 / p50 两线（ms）。
 *   4. 并发·排队趋势：受控 gauge:<name>（concurrency./queue./backlog. 前缀，对齐
 *      metric_sampling._GAUGE_NAMES）多线。
 *
 * 数据：@tanstack/vue-query 按 timeRange/step 拉数（keepPreviousData，watch 重查）；
 * 每图加载骨架 + 空态友好；degraded（SQLite 近似分位）时标题旁标注。
 *
 * 复用抉择：`analytics/DurationDistribution` 走 inject('analyticsDateRange') + 独立
 * `/analytics/duration-distribution/` 端点，入参与本页 timeRange + queryMetrics 不匹配，
 * 故时长趋势按 UI-SPEC 兜底自渲染分位折线（queryMetrics duration p95/p50）。
 */
import type { MetricDimension, MetricName, MetricPoint, MetricsQueryResult } from '~/api/system'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { queryMetrics } from '~/api/system'
import {
  axisLabelStyle,
  axisLineStyle,
  chartGrid,
  legendTextStyle,
  splitLineStyle,
  tooltipStyle,
} from '~/components/analytics/chart-theme'
import ChartCard from '~/components/analytics/ChartCard.vue'
import { VChart } from '~/components/analytics/echarts-setup'
import { formatClock } from '~/components/observability/format'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Skeleton } from '~/components/ui/skeleton'

const props = withDefaults(defineProps<{
  timeRange: { start: string, end: string }
  step?: string
}>(), {
  step: '',
})

// 多系列调色板（与既有大盘色调一致，亮暗自适配靠透明度区分）。
const PALETTE = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ec4899', '#14b8a6', '#6366f1', '#ef4444']

/** 按时间跨度推导步长（无显式 step 时）：控制桶数在可读范围。 */
const effectiveStep = computed(() => {
  if (props.step)
    return props.step
  const start = new Date(props.timeRange.start).getTime()
  const end = new Date(props.timeRange.end).getTime()
  const spanMs = Math.max(0, end - start)
  if (spanMs <= 10 * 60_000)
    return '30s'
  if (spanMs <= 2 * 60 * 60_000)
    return '1m'
  if (spanMs <= 24 * 60 * 60_000)
    return '5m'
  return '1h'
})

function useTrendQuery(
  keyPrefix: string,
  metric: () => MetricName,
  dimension: () => MetricDimension | '',
  agg?: () => 'p95' | 'p90' | 'p50' | 'avg' | 'max',
) {
  return useQuery({
    queryKey: [keyPrefix, metric, dimension, () => props.timeRange, effectiveStep, agg ?? (() => undefined)],
    queryFn: async () => {
      return queryMetrics({
        metric: metric(),
        dimension: dimension(),
        start: props.timeRange.start,
        end: props.timeRange.end,
        step: effectiveStep.value,
        agg: agg?.(),
      })
    },
    placeholderData: keepPreviousData,
    staleTime: 5000,
  })
}

/** 把 series 按 dim 分组、按 bucket 对齐，输出 echarts categories + 每 dim 一条 data。 */
function groupByDim(
  result: MetricsQueryResult<MetricPoint> | undefined,
  opts: { rate?: boolean } = {},
): { categories: string[], series: { name: string, data: (number | null)[] }[] } {
  if (!result?.series?.length)
    return { categories: [], series: [] }
  const step = result.step_seconds || 1
  const bucketSet = new Set<string>()
  const dimMap = new Map<string, Map<string, number>>()
  for (const p of result.series) {
    bucketSet.add(p.bucket)
    const dim = p.dim || 'overall'
    if (!dimMap.has(dim))
      dimMap.set(dim, new Map())
    const v = opts.rate ? (p.value ?? 0) / step : (p.value ?? 0)
    dimMap.get(dim)!.set(p.bucket, v)
  }
  const categories = [...bucketSet].sort()
  const series = [...dimMap.entries()].map(([dim, byBucket]) => ({
    name: dim,
    data: categories.map(b => byBucket.get(b) ?? null),
  }))
  return { categories, series }
}

function baseLineOption(categories: string[], legend: string[], extra: Record<string, any> = {}) {
  return {
    tooltip: { trigger: 'axis' as const, ...tooltipStyle },
    legend: { data: legend, textStyle: legendTextStyle, icon: 'circle', itemWidth: 8, itemHeight: 8, top: 0 },
    grid: chartGrid,
    xAxis: {
      type: 'category' as const,
      data: categories.map(formatClock),
      boundaryGap: false,
      axisLine: axisLineStyle,
      axisLabel: axisLabelStyle,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      axisLine: { show: false },
      axisLabel: axisLabelStyle,
      splitLine: splitLineStyle,
    },
    ...extra,
  }
}

function lineSeries(name: string, data: (number | null)[], color: string, opts: { dashed?: boolean, yAxisIndex?: number } = {}) {
  return {
    name,
    type: 'line' as const,
    data,
    smooth: true,
    showSymbol: false,
    connectNulls: true,
    yAxisIndex: opts.yAxisIndex ?? 0,
    lineStyle: { color, width: 2, type: opts.dashed ? ('dashed' as const) : ('solid' as const) },
    itemStyle: { color },
  }
}

// ── 1) 吞吐趋势（QPS per dim + 总 TPS 副轴），维度可切 ──────────────────────
const throughputDim = ref<'provider' | 'call_source'>('provider')
const { data: qpsData, isLoading: qpsLoading } = useTrendQuery('obs-trend-qps', () => 'qps', () => throughputDim.value)
const { data: tpsData, isLoading: tpsLoading } = useTrendQuery('obs-trend-tps', () => 'tps', () => '')

const throughputOption = computed(() => {
  const qps = groupByDim(qpsData.value, { rate: true })
  const tps = groupByDim(tpsData.value, { rate: true })
  // 总 TPS：把 tps 所有 dim 同 bucket 相加（dimension='' 通常单 dim，稳妥再聚合）。
  const categories = qps.categories.length ? qps.categories : tps.categories
  const tpsTotal = categories.map((_, i) =>
    tps.series.reduce((s, ser) => s + (ser.data[i] ?? 0), 0),
  )
  const legend = [...qps.series.map(s => `QPS·${s.name}`), 'TPS(千)']
  return {
    ...baseLineOption(categories, legend, {
      yAxis: [
        { type: 'value' as const, name: 'QPS', axisLine: { show: false }, axisLabel: axisLabelStyle, splitLine: splitLineStyle },
        { type: 'value' as const, name: 'TPS(千)', position: 'right' as const, axisLine: { show: false }, axisLabel: axisLabelStyle, splitLine: { show: false } },
      ],
    }),
    series: [
      ...qps.series.map((s, i) => lineSeries(`QPS·${s.name}`, s.data, PALETTE[i % PALETTE.length])),
      lineSeries('TPS(千)', tpsTotal.map(v => v / 1000), '#94a3b8', { dashed: true, yAxisIndex: 1 }),
    ],
  }
})
const throughputEmpty = computed(() => !qpsData.value?.series?.length && !tpsData.value?.series?.length)
const throughputLoading = computed(() => (qpsLoading.value && !qpsData.value) || (tpsLoading.value && !tpsData.value))

// ── 2) 错误趋势（系统 / 上游 / 业务限制 三线）─────────────────────────────
const { data: errorData, isLoading: errorLoading } = useTrendQuery('obs-trend-error', () => 'error', () => 'error_class')
const ERROR_CLASS_LABEL: Record<string, string> = { system: '系统', upstream: '上游', business: '业务限制' }
const ERROR_CLASS_COLOR: Record<string, string> = { system: '#ef4444', upstream: '#f59e0b', business: '#6366f1' }

const errorOption = computed(() => {
  const grouped = groupByDim(errorData.value)
  const categories = grouped.categories
  const classes = ['system', 'upstream', 'business']
  const byDim = new Map(grouped.series.map(s => [s.name, s.data]))
  const legend = classes.map(c => ERROR_CLASS_LABEL[c])
  return {
    ...baseLineOption(categories, legend),
    series: classes.map(c =>
      lineSeries(ERROR_CLASS_LABEL[c], (byDim.get(c) ?? categories.map(() => 0)).map(v => v ?? 0), ERROR_CLASS_COLOR[c]),
    ),
  }
})
const errorEmpty = computed(() => !errorData.value?.series?.length)

// ── 3) 请求时长趋势（p95 / p50，ms）──────────────────────────────────────
const { data: durP95, isLoading: durP95Loading } = useTrendQuery('obs-trend-dur-p95', () => 'duration', () => '', () => 'p95')
const { data: durP50 } = useTrendQuery('obs-trend-dur-p50', () => 'duration', () => '', () => 'p50')

const durationDegraded = computed(() => durP95.value?.degraded === true)
const durationOption = computed(() => {
  const p95 = groupByDim(durP95.value)
  const p50 = groupByDim(durP50.value)
  const categories = p95.categories.length ? p95.categories : p50.categories
  const p95Data = p95.series[0]?.data ?? []
  const p50Data = p50.series[0]?.data ?? []
  return {
    ...baseLineOption(categories, ['P95', 'P50']),
    series: [
      lineSeries('P95', p95Data, '#f59e0b'),
      lineSeries('P50', p50Data, '#3b82f6'),
    ],
  }
})
const durationEmpty = computed(() => !durP95.value?.series?.length && !durP50.value?.series?.length)
const durationLoading = computed(() => durP95Loading.value && !durP95.value)

// ── 4) 并发·排队趋势（受控 gauge:<name> 多线）────────────────────────────
const GAUGES: { name: string, label: string }[] = [
  { name: 'concurrency.provider_slots', label: 'Provider 槽位' },
  { name: 'concurrency.rag', label: 'RAG 并发' },
  { name: 'queue.durable_todo', label: '队列待处理' },
  { name: 'queue.durable_doing', label: '队列处理中' },
  { name: 'backlog.subagent_active', label: '容器任务积压' },
]
const { data: gaugeData, isLoading: gaugeLoading } = useQuery({
  queryKey: ['obs-trend-gauge', () => props.timeRange, effectiveStep],
  queryFn: async () => {
    const results = await Promise.all(
      GAUGES.map(g => queryMetrics({
        metric: `gauge:${g.name}` as MetricName,
        start: props.timeRange.start,
        end: props.timeRange.end,
        step: effectiveStep.value,
        agg: 'avg',
      }).catch(() => null)),
    )
    return results
  },
  placeholderData: keepPreviousData,
  staleTime: 5000,
})

const gaugeOption = computed(() => {
  const results = gaugeData.value ?? []
  // 取所有非空 gauge 的 bucket 并集对齐。
  const bucketSet = new Set<string>()
  results.forEach((r) => {
    r?.series?.forEach((p: MetricPoint) => bucketSet.add(p.bucket))
  })
  const categories = [...bucketSet].sort()
  const present: { label: string, data: (number | null)[], color: string }[] = []
  results.forEach((r, idx) => {
    if (!r?.series?.length)
      return
    const byBucket = new Map<string, number>()
    for (const p of r.series)
      byBucket.set(p.bucket, p.value ?? 0)
    present.push({
      label: GAUGES[idx].label,
      data: categories.map(b => byBucket.get(b) ?? null),
      color: PALETTE[idx % PALETTE.length],
    })
  })
  return {
    ...baseLineOption(categories, present.map(p => p.label)),
    series: present.map(p => lineSeries(p.label, p.data, p.color)),
  }
})
const gaugeEmpty = computed(() => (gaugeData.value ?? []).every(r => !r?.series?.length))
</script>

<template>
  <div class="grid gap-4 lg:grid-cols-2">
    <!-- 吞吐趋势 -->
    <ChartCard
      title="吞吐趋势"
      description="各维度 QPS 与总 TPS（千）"
      icon="lucide--trending-up"
      icon-class="bg-blue-500/10 text-blue-600"
    >
      <template #actions>
        <Select v-model="throughputDim">
          <SelectTrigger class="h-8 w-[120px] rounded-lg bg-background/90" aria-label="吞吐分组维度">
            <span class="icon-[lucide--layout-grid] mr-1.5 text-sm text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="provider">
              按 Provider
            </SelectItem>
            <SelectItem value="call_source">
              按调用来源
            </SelectItem>
          </SelectContent>
        </Select>
      </template>
      <Skeleton v-if="throughputLoading" class="h-[260px] w-full rounded-lg" />
      <div v-else-if="throughputEmpty" class="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <span class="icon-[lucide--line-chart] text-3xl opacity-30" />
        <span class="text-sm">当前时段无数据</span>
      </div>
      <VChart v-else :option="throughputOption" style="height: 260px" autoresize />
    </ChartCard>

    <!-- 错误趋势 -->
    <ChartCard
      title="错误趋势"
      description="系统 / 上游 / 业务限制三口径"
      icon="lucide--triangle-alert"
      icon-class="bg-rose-500/10 text-rose-600"
    >
      <Skeleton v-if="errorLoading && !errorData" class="h-[260px] w-full rounded-lg" />
      <div v-else-if="errorEmpty" class="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <span class="icon-[lucide--shield-check] text-3xl opacity-30" />
        <span class="text-sm">当前时段无错误</span>
      </div>
      <VChart v-else :option="errorOption" style="height: 260px" autoresize />
    </ChartCard>

    <!-- 请求时长趋势 -->
    <ChartCard
      title="请求时长趋势"
      :description="durationDegraded ? '分位为近似值（SQLite）' : 'P95 / P50 分位（毫秒）'"
      icon="lucide--timer"
      icon-class="bg-amber-500/10 text-amber-600"
    >
      <template v-if="durationDegraded" #actions>
        <span
          class="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-600"
          title="SQLite 下分位为近似值"
        >
          <span class="icon-[lucide--info] text-xs" />
          近似分位
        </span>
      </template>
      <Skeleton v-if="durationLoading" class="h-[260px] w-full rounded-lg" />
      <div v-else-if="durationEmpty" class="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <span class="icon-[lucide--line-chart] text-3xl opacity-30" />
        <span class="text-sm">当前时段无数据</span>
      </div>
      <VChart v-else :option="durationOption" style="height: 260px" autoresize />
    </ChartCard>

    <!-- 并发·排队趋势 -->
    <ChartCard
      title="并发 · 排队趋势"
      description="Provider 槽位 / 队列深 / 容器积压"
      icon="lucide--layers"
      icon-class="bg-violet-500/10 text-violet-600"
    >
      <Skeleton v-if="gaugeLoading && !gaugeData" class="h-[260px] w-full rounded-lg" />
      <div v-else-if="gaugeEmpty" class="flex h-[260px] flex-col items-center justify-center gap-2 text-muted-foreground">
        <span class="icon-[lucide--line-chart] text-3xl opacity-30" />
        <span class="text-sm">当前时段无数据</span>
      </div>
      <VChart v-else :option="gaugeOption" style="height: 260px" autoresize />
    </ChartCard>
  </div>
</template>
