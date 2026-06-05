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
      backgroundColor: 'rgba(17, 24, 39, 0.9)',
      borderColor: 'rgba(75, 85, 99, 0.3)',
      textStyle: { color: '#e5e7eb' },
    },
    legend: {
      data: ['输入 Token', '输出 Token', '成本 (USD)'],
      textStyle: { color: '#9ca3af' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: points.map(p => p.date),
      axisLine: { lineStyle: { color: '#374151' } },
      axisLabel: { color: '#9ca3af' },
    },
    yAxis: [
      {
        type: 'value' as const,
        name: 'Tokens',
        nameTextStyle: { color: '#9ca3af' },
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: { color: '#9ca3af' },
        splitLine: { lineStyle: { color: '#1f2937' } },
      },
      {
        type: 'value' as const,
        name: 'USD',
        nameTextStyle: { color: '#9ca3af' },
        axisLine: { lineStyle: { color: '#374151' } },
        axisLabel: {
          color: '#9ca3af',
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
        itemStyle: { color: '#3b82f6', borderRadius: [0, 0, 0, 0] },
        barMaxWidth: 30,
      },
      {
        name: '输出 Token',
        type: 'bar' as const,
        stack: 'tokens',
        data: points.map(p => p.output_tokens),
        itemStyle: { color: '#06b6d4', borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 30,
      },
      {
        name: '成本 (USD)',
        type: 'line' as const,
        yAxisIndex: 1,
        smooth: true,
        lineStyle: { color: '#8b5cf6', width: 2 },
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
      backgroundColor: 'rgba(17, 24, 39, 0.9)',
      borderColor: 'rgba(75, 85, 99, 0.3)',
      textStyle: { color: '#e5e7eb' },
    },
    legend: {
      data: presentProviders.map(pt => PROVIDER_LABELS[pt] ?? pt),
      textStyle: { color: '#9ca3af' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category' as const,
      data: allDates,
      axisLine: { lineStyle: { color: '#374151' } },
      axisLabel: { color: '#9ca3af' },
    },
    yAxis: {
      type: 'value' as const,
      name: 'USD',
      nameTextStyle: { color: '#9ca3af' },
      axisLine: { lineStyle: { color: '#374151' } },
      axisLabel: {
        color: '#9ca3af',
        // eslint-disable-next-line no-template-curly-in-string
        formatter: '${value}',
      },
      splitLine: { lineStyle: { color: '#1f2937' } },
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
  <div class="card p-6 transition-all duration-200 hover:shadow-lg hover:border-primary/30">
    <h3 class="text-sm font-medium text-muted-foreground mb-4">
      {{ grouping === 'provider_type' ? 'Token 成本趋势（按 Provider）' : 'Token 消耗 / 成本趋势' }}
    </h3>
    <Skeleton v-if="isLoading" class="h-[300px] w-full" />
    <div v-else-if="!hasData" class="h-[300px] flex items-center justify-center text-muted-foreground">
      暂无 Token 数据
    </div>
    <VChart v-else :option="chartOption" style="height: 300px" autoresize />
  </div>
</template>
