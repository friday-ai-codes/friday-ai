<script setup lang="ts">
import { computed, inject, type Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import api from '~/api/client'
import { VChart } from '~/components/analytics/echarts-setup'
import { Skeleton } from '~/components/ui/skeleton'
interface TokenCostDataPoint {
 date: string
 input_tokens: number
 output_tokens: number
 total_cost_usd: number
}
const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!
const queryParams = computed( => ({
 date_from: dateRange.value.from,
 date_to: dateRange.value.to,
}))
const { data, isLoading } = useQuery({
 queryKey: ['analytics-token-cost', queryParams],
 queryFn: async => {
 return await api.get<TokenCostDataPoint>('/analytics/token-cost/', queryParams.value)
 },
 placeholderData: keepPreviousData,
})
const chartOption = computed( => {
 const points = data.value ||
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
 grid: {
 left: '3%',
 right: '4%',
 bottom: '3%',
 containLabel: true,
 },
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
</script>
<template>
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl transition-all duration-200 hover:shadow-lg hover:border-primary/30">
 <h3 class="text-sm font-medium text-muted-foreground mb-4">Token 消耗 / 成本趋势</h3>
 <Skeleton v-if="isLoading" class="h-[300px] w-full" />
 <div v-else-if="!data?.length" class="h-[300px] flex items-center justify-center text-muted-foreground">
 暂无 Token 数据
 </div>
 <VChart v-else:option="chartOption" style="height: 300px" autoresize />
 </div>
</template>
