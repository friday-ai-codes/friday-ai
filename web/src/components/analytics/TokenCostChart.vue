<script setup lang="ts">
/**
 * Analytics Token 成本图表（ — / ）
 *
 * 两种模式：
 * - grouping === 'none'：原 3 层 series（输入 / 输出 / 成本折线）
 * - grouping === 'provider_type'：按 Provider 堆叠柱状图，颜色从 providerBrandColors.ts 注入
 */

import type { Ref } from 'vue'
import type { AnalyticsGrouping } from '~/stores/analyticsFilters'
import type { ProviderType } from '~/types/providerCredential'
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
import { getProviderBrandColor } from '~/lib/providerBrandColors'

interface TokenCostDataPoint {
  date: string
  input_tokens: number
  output_tokens: number
  total_cost_usd: number
}

interface TokenCostGrouped {
  group_by: 'provider_type' | 'project' | 'none'
  groups: Record<string, TokenCostDataPoint[]>
}

interface Props {
  grouping?: AnalyticsGrouping
}

const props = withDefaults(defineProps<Props>(), { grouping: 'none' })

const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!

const queryParams = computed(() => ({
  date_from: dateRange.value.from,
  date_to: dateRange.value.to,
}))

const groupingRef = computed(() => props.grouping)

const { data, isLoading } = useQuery({
  queryKey: ['analytics-token-cost', queryParams, groupingRef],
  queryFn: async () => {
    if (groupingRef.value === 'none')
      return await api.get<TokenCostDataPoint[]>('/analytics/token-cost/', queryParams.value)
    return await api.get<TokenCostGrouped>('/analytics/token-cost/', {
      ...queryParams.value,
      group_by: groupingRef.value,
    })
  },
  placeholderData: keepPreviousData,
})

// Provider 中文名映射（与 UI-SPEC §Copywriting L285 一致）
const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  openai_chat: 'OpenAI（Chat）',
  openai_responses: 'OpenAI（Responses）',
  gemini: 'Gemini',
  ollama: 'Ollama',
  unknown: '未知',
}

// ---- grouping=none：原 3 层 series ----
const flatChartOption = computed(() => {
  const points = Array.isArray(data.value) ? (data.value as TokenCostDataPoint[]) : []
  return {
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipStyle,
    },
    legend: {
      data: ['输入 Token', '输出 Token', '成本 (USD)'],
      textStyle: legendTextStyle,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
    },
    grid: chartGrid,
    xAxis: {
      type: 'category' as const,
      data: points.map(p => p.date),
      axisLine: axisLineStyle,
      axisLabel: axisLabelStyle,
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value' as const,
        name: 'Tokens',
        nameTextStyle: { color: '#94a3b8', fontSize: 11 },
        axisLine: { show: false },
        axisLabel: axisLabelStyle,
        splitLine: splitLineStyle,
      },
      {
        type: 'value' as const,
        name: 'USD',
        nameTextStyle: { color: '#94a3b8', fontSize: 11 },
        axisLine: { show: false },
        axisLabel: {
          ...axisLabelStyle,
          // eslint-disable-next-line no-template-curly-in-string
          formatter: '${value}',
        },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '输入 Token',
        type: 'bar' as const,
        stack: 'tokens',
        data: points.map(p => p.input_tokens),
        itemStyle: { color: '#38bdf8', borderRadius: [0, 0, 0, 0] },
        barMaxWidth: 28,
      },
      {
        name: '输出 Token',
        type: 'bar' as const,
        stack: 'tokens',
        data: points.map(p => p.output_tokens),
        itemStyle: { color: '#0ea5e9', borderRadius: [6, 6, 0, 0] },
        barMaxWidth: 28,
      },
      {
        name: '成本 (USD)',
        type: 'line' as const,
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        showSymbol: false,
        lineStyle: { color: '#8b5cf6', width: 2.5 },
        itemStyle: { color: '#8b5cf6' },
        data: points.map(p => p.total_cost_usd),
      },
    ],
  }
})

// ---- grouping=provider_type：按 Provider 堆叠柱状图，品牌色注入 ----
const stackedChartOption = computed(() => {
  const grouped = data.value as TokenCostGrouped | undefined
  if (!grouped?.groups)
    return { series: [], xAxis: { data: [] }, yAxis: {} }

  // 字典序
  const orderedProviders: (ProviderType | 'unknown')[] = [
    'anthropic',
    'gemini',
    'ollama',
    'openai_chat',
    'openai_responses',
    'unknown',
  ]
  const presentProviders = orderedProviders.filter(pt => grouped.groups[pt])

  // 汇总所有日期（多 Provider 的日期并集）
  const allDates = Array.from(
    new Set(
      presentProviders.flatMap(pt => grouped.groups[pt].map(p => p.date)),
    ),
  ).sort()

  // 为每个 Provider 构建按 allDates 对齐的 cost 数组
  const series = presentProviders.map((pt) => {
    const points = grouped.groups[pt]
    const byDate = new Map(points.map(p => [p.date, p.total_cost_usd]))
    const color = getProviderBrandColor(pt === 'unknown' ? null : pt)
    return {
      name: PROVIDER_LABELS[pt] ?? pt,
      type: 'bar' as const,
      stack: 'total',
      data: allDates.map(d => byDate.get(d) ?? 0),
      itemStyle: { color: color.hex },
      barMaxWidth: 30,
    }
  })

  return {
    tooltip: {
      trigger: 'axis' as const,
      ...tooltipStyle,
    },
    legend: {
      data: presentProviders.map(pt => PROVIDER_LABELS[pt] ?? pt),
      textStyle: legendTextStyle,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
    },
    grid: chartGrid,
    xAxis: {
      type: 'category' as const,
      data: allDates,
      axisLine: axisLineStyle,
      axisLabel: axisLabelStyle,
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      name: 'USD',
      nameTextStyle: { color: '#94a3b8', fontSize: 11 },
      axisLine: { show: false },
      axisLabel: {
        ...axisLabelStyle,
        // eslint-disable-next-line no-template-curly-in-string
        formatter: '${value}',
      },
      splitLine: splitLineStyle,
    },
    series,
  }
})

const chartOption = computed(() =>
  props.grouping === 'provider_type' ? stackedChartOption.value : flatChartOption.value,
)

const hasData = computed(() => {
  if (props.grouping === 'provider_type') {
    const grouped = data.value as TokenCostGrouped | undefined
    return grouped?.groups && Object.keys(grouped.groups).length > 0
  }
  return Array.isArray(data.value) && (data.value as TokenCostDataPoint[]).length > 0
})
</script>

<template>
  <ChartCard
    :title="grouping === 'provider_type' ? 'Token 成本趋势（按 Provider）' : 'Token 消耗 / 成本趋势'"
    description="模型调用的 Token 与成本走势"
    icon="lucide--coins"
    icon-class="bg-violet-500/10 text-violet-600"
  >
    <Skeleton v-if="isLoading" class="h-[300px] w-full rounded-lg" />
    <div v-else-if="!hasData" class="h-[300px] flex flex-col items-center justify-center gap-2 text-muted-foreground">
      <span class="icon-[lucide--coins] text-3xl opacity-30" />
      <span class="text-sm">暂无 Token 数据</span>
    </div>
    <VChart v-else :option="chartOption" style="height: 300px" autoresize />
  </ChartCard>
</template>
