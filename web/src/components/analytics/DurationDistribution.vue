<script setup lang="ts">
import type { Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import api from '~/api/client'
import {
  axisLabelStyle,
  axisLineStyle,
  chartGrid,
  splitLineStyle,
  tooltipStyle,
} from '~/components/analytics/chart-theme'
import ChartCard from '~/components/analytics/ChartCard.vue'
import { VChart } from '~/components/analytics/echarts-setup'
import { Skeleton } from '~/components/ui/skeleton'

interface DurationBucket {
  bucket_label: string
  count: number
}

const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!

const queryParams = computed(() => ({
  date_from: dateRange.value.from,
  date_to: dateRange.value.to,
}))

const { data, isLoading } = useQuery({
  queryKey: ['analytics-duration-distribution', queryParams],
  queryFn: async () => {
    return await api.get<DurationBucket[]>('/analytics/duration-distribution/', queryParams.value)
  },
  placeholderData: keepPreviousData,
})

const chartOption = computed(() => {
  const buckets = data.value || []
  return {
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipStyle,
    },
    grid: { ...chartGrid, top: 20 },
    xAxis: {
      type: 'category' as const,
      data: buckets.map(b => b.bucket_label),
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
        type: 'bar' as const,
        data: buckets.map(b => b.count),
        itemStyle: {
          color: {
            type: 'linear' as const,
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: '#14b8a6' },
              { offset: 1, color: '#0d9488' },
            ],
          },
          borderRadius: [6, 6, 0, 0],
        },
        barMaxWidth: 36,
      },
    ],
  }
})
</script>

<template>
  <ChartCard
    title="执行时长分布"
    description="按时长区间统计的执行次数"
    icon="lucide--bar-chart-2"
    icon-class="bg-teal-500/10 text-teal-600"
  >
    <Skeleton v-if="isLoading" class="h-[300px] w-full rounded-lg" />
    <div v-else-if="!data?.some(b => b.count > 0)" class="h-[300px] flex flex-col items-center justify-center gap-2 text-muted-foreground">
      <span class="icon-[lucide--bar-chart-2] text-3xl opacity-30" />
      <span class="text-sm">暂无执行数据</span>
    </div>
    <VChart v-else :option="chartOption" style="height: 300px" autoresize />
  </ChartCard>
</template>
