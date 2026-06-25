<script setup lang="ts">
/**
 * 实时速率卡（UI-SPEC §2.2）：窗口 tab（1min/5min/30min/1h）+ 当前/峰值/平均 QPS·TPS
 * 三联 + sparkline 迷你趋势。
 *
 * 语义：速率卡是「实时滚动窗口」，与页面统一时间范围解耦——本组件自管窗口 tab 并
 * 按 now 反推 start/step，用 @tanstack/vue-query 拉 queryMetrics(qps|tps)，短窗口配
 * refetchInterval 实现轻量实时刷新（不复用页面 4s 定时器）。
 *
 * 口径：metric=qps 的桶值为该桶内请求数、metric=tps 的桶值为该桶内 token 数；
 *   速率 = 桶值 / step_seconds。当前=最后一桶速率、峰值=max、平均=mean。
 */
import type { MetricPoint, MetricsQueryResult } from '~/api/system'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { queryMetrics } from '~/api/system'
import { tooltipStyle } from '~/components/analytics/chart-theme'
import { VChart } from '~/components/analytics/echarts-setup'
import { formatNumber, formatThousands } from '~/components/observability/format'
import { Skeleton } from '~/components/ui/skeleton'

type WindowKey = '1min' | '5min' | '30min' | '1h'

interface WindowSpec {
  key: WindowKey
  label: string
  /** 窗口跨度（毫秒）。 */
  spanMs: number
  /** 桶步长（秒）。 */
  stepSec: number
  /** 轻量实时刷新间隔（毫秒）。 */
  refetchMs: number
}

// 窗口 → 步长/刷新间隔（注释量级，平衡桶数与实时性）。
const WINDOWS: WindowSpec[] = [
  { key: '1min', label: '1 分钟', spanMs: 60_000, stepSec: 5, refetchMs: 4000 },
  { key: '5min', label: '5 分钟', spanMs: 5 * 60_000, stepSec: 15, refetchMs: 5000 },
  { key: '30min', label: '30 分钟', spanMs: 30 * 60_000, stepSec: 60, refetchMs: 15_000 },
  { key: '1h', label: '1 小时', spanMs: 60 * 60_000, stepSec: 120, refetchMs: 30_000 },
]

const activeKey = ref<WindowKey>('5min')
const activeWindow = computed(() => WINDOWS.find(w => w.key === activeKey.value)!)

function rangeFor(spec: WindowSpec) {
  const now = Date.now()
  return {
    start: new Date(now - spec.spanMs).toISOString(),
    end: new Date(now).toISOString(),
    step: `${spec.stepSec}s`,
  }
}

function buildQuery(metric: 'qps' | 'tps') {
  return useQuery({
    queryKey: ['obs-rate', metric, activeKey],
    queryFn: async () => {
      const spec = activeWindow.value
      const { start, end, step } = rangeFor(spec)
      return queryMetrics({ metric, start, end, step, dimension: '' })
    },
    placeholderData: keepPreviousData,
    refetchInterval: () => activeWindow.value.refetchMs,
    staleTime: 2000,
  })
}

const { data: qpsData, isLoading: qpsLoading } = buildQuery('qps')
const { data: tpsData, isLoading: tpsLoading } = buildQuery('tps')

interface RateStats {
  current: number
  peak: number
  avg: number
  spark: number[]
}

/** 把 series 按 bucket 聚合各 dim 之和，再除以 step 得速率序列，派生 current/peak/avg。 */
function deriveStats(result: MetricsQueryResult<MetricPoint> | undefined): RateStats {
  const empty: RateStats = { current: 0, peak: 0, avg: 0, spark: [] }
  if (!result?.series?.length)
    return empty
  const step = result.step_seconds || 1
  const byBucket = new Map<string, number>()
  for (const p of result.series)
    byBucket.set(p.bucket, (byBucket.get(p.bucket) ?? 0) + (p.value ?? 0))
  const buckets = [...byBucket.keys()].sort()
  const rates = buckets.map(b => (byBucket.get(b) ?? 0) / step)
  if (!rates.length)
    return empty
  const current = rates[rates.length - 1]
  const peak = Math.max(...rates)
  const avg = rates.reduce((s, v) => s + v, 0) / rates.length
  return { current, peak, avg, spark: rates }
}

const qps = computed(() => deriveStats(qpsData.value))
const tps = computed(() => deriveStats(tpsData.value))

function sparkOption(values: number[], color: string) {
  return {
    grid: { left: 2, right: 2, top: 4, bottom: 2, containLabel: false },
    xAxis: { type: 'category' as const, show: false, data: values.map((_, i) => i), boundaryGap: false },
    yAxis: { type: 'value' as const, show: false, min: 0 },
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipStyle,
      axisPointer: { type: 'none' as const },
      formatter: (params: any) => {
        const v = params?.[0]?.value ?? 0
        return `${formatNumber(v, 2)} /s`
      },
    },
    series: [{
      type: 'line' as const,
      data: values,
      smooth: true,
      showSymbol: false,
      lineStyle: { color, width: 2 },
      areaStyle: {
        color: {
          type: 'linear' as const,
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: `${color}33` },
            { offset: 1, color: `${color}00` },
          ],
        },
      },
    }],
  }
}

const qpsSpark = computed(() => sparkOption(qps.value.spark, '#3b82f6'))
const tpsSpark = computed(() => sparkOption(tps.value.spark, '#8b5cf6'))

const loading = computed(() => (qpsLoading.value && !qpsData.value) || (tpsLoading.value && !tpsData.value))
</script>

<template>
  <div class="flex h-full flex-col gap-4 rounded-xl border border-border/70 bg-card p-5">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <span class="icon-[lucide--activity] text-base text-primary" />
        实时速率
      </div>
      <div
        class="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5"
        role="tablist"
        aria-label="实时速率窗口"
      >
        <button
          v-for="w in WINDOWS"
          :key="w.key"
          type="button"
          role="tab"
          :aria-selected="activeKey === w.key"
          class="cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          :class="activeKey === w.key
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'"
          @click="activeKey = w.key"
        >
          {{ w.label }}
        </button>
      </div>
    </div>

    <div class="grid flex-1 gap-4 sm:grid-cols-2">
      <!-- QPS -->
      <div class="space-y-2.5 rounded-lg border border-border/50 bg-muted/20 p-3.5">
        <div class="flex items-center gap-1.5 text-xs font-semibold text-blue-500">
          <span class="icon-[lucide--gauge] text-sm" />
          QPS
          <span class="font-normal text-muted-foreground">每秒请求</span>
        </div>
        <template v-if="loading">
          <Skeleton class="h-7 w-20" />
          <Skeleton class="h-10 w-full" />
        </template>
        <template v-else>
          <div class="flex items-end gap-3">
            <div>
              <div class="text-2xl font-bold tabular-nums text-blue-500">
                {{ formatNumber(qps.current, 2) }}
              </div>
              <div class="text-[11px] text-muted-foreground">
                当前
              </div>
            </div>
          </div>
          <VChart :option="qpsSpark" style="height: 40px" autoresize />
          <div class="flex justify-between border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
            <span>峰值 <b class="tabular-nums text-foreground/80">{{ formatNumber(qps.peak, 2) }}</b></span>
            <span>平均 <b class="tabular-nums text-foreground/80">{{ formatNumber(qps.avg, 2) }}</b></span>
          </div>
        </template>
      </div>

      <!-- TPS -->
      <div class="space-y-2.5 rounded-lg border border-border/50 bg-muted/20 p-3.5">
        <div class="flex items-center gap-1.5 text-xs font-semibold text-violet-500">
          <span class="icon-[lucide--zap] text-sm" />
          TPS
          <span class="font-normal text-muted-foreground">每秒 Token</span>
        </div>
        <template v-if="loading">
          <Skeleton class="h-7 w-20" />
          <Skeleton class="h-10 w-full" />
        </template>
        <template v-else>
          <div class="flex items-end gap-3">
            <div>
              <div class="text-2xl font-bold tabular-nums text-violet-500">
                {{ formatThousands(tps.current) }}
              </div>
              <div class="text-[11px] text-muted-foreground">
                当前
              </div>
            </div>
          </div>
          <VChart :option="tpsSpark" style="height: 40px" autoresize />
          <div class="flex justify-between border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
            <span>峰值 <b class="tabular-nums text-foreground/80">{{ formatThousands(tps.peak) }}</b></span>
            <span>平均 <b class="tabular-nums text-foreground/80">{{ formatThousands(tps.avg) }}</b></span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
