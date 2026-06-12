<script setup lang="ts">
import type { Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import api from '~/api/client'
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
import { Skeleton } from '~/components/ui/skeleton'

interface TrendDataPoint {
  date: string
  completed: number
  failed: number
  total: number
}

const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!

const queryParams = computed(() => ({
  date_from: dateRange.value.from,
  date_to: dateRange.value.to,
}))

const { data, isLoading } = useQuery({
  queryKey: ['analytics-trends', queryParams],
  queryFn: async () => {
    return await api.get<TrendDataPoint[]>('/analytics/trends/', queryParams.value)
  },
  placeholderData: keepPreviousData,
})

const chartOption = computed(() => {
  const points = data.value || []
  return {
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipStyle,
    },
    legend: {
      data: ['已完成', '失败'],
      textStyle: legendTextStyle,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
    },
    grid: chartGrid,
    xAxis: {
      type: 'category' as const,
      data: points.map(p => p.date),
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
    series: [
      {
        name: '已完成',
        type: 'line' as const,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: false,
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(16, 185, 129, 0.28)' },
              { offset: 1, color: 'rgba(16, 185, 129, 0.02)' },
            ],
          },
        },
        lineStyle: { color: '#10b981', width: 2.5 },
        itemStyle: { color: '#10b981' },
        data: points.map(p => p.completed),
      },
      {
        name: '失败',
        type: 'line' as const,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: false,
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(239, 68, 68, 0.22)' },
              { offset: 1, color: 'rgba(239, 68, 68, 0.02)' },
            ],
          },
        },
        lineStyle: { color: '#ef4444', width: 2.5 },
        itemStyle: { color: '#ef4444' },
        data: points.map(p => p.failed),
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="成功/失败趋势"
    description="每日完成与失败执行数"
    icon="lucide--trending-up"
    icon-class="bg-emerald-500/10 text-emerald-600"
  >
    <Skeleton v-if="isLoading" class="h-[300px] w-full rounded-lg" />
    <div v-else-if="!data?.length" class="h-[300px] flex flex-col items-center justify-center gap-2 text-muted-foreground">
      <span class="icon-[lucide--line-chart] text-3xl opacity-30" />
      <span class="text-sm">暂无执行数据</span>
    </div>
    <VChart v-else :option="chartOption" style="height: 300px" autoresize />
  </ChartCard>
</template>
