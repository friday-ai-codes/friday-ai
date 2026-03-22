<script setup lang="ts">
import type { Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import api from '~/api/client'
import { VChart } from '~/components/analytics/echarts-setup'
import { Skeleton } from '~/components/ui/skeleton'
interface TrendDataPoint {
 date: string
 completed: number
 failed: number
 total: number
}
const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!
const queryParams = computed( => ({
 date_from: dateRange.value.from,
 date_to: dateRange.value.to,
}))
const { data, isLoading } = useQuery({
 queryKey: ['analytics-trends', queryParams],
 queryFn: async => {
 return await api.get<TrendDataPoint>('/analytics/trends/', queryParams.value)
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
 data: ['已完成', '失败'],
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
 yAxis: {
 type: 'value' as const,
 axisLine: { lineStyle: { color: '#374151' } },
 axisLabel: { color: '#9ca3af' },
 splitLine: { lineStyle: { color: '#1f2937' } },
 },
 series: [
 {
 name: '已完成',
 type: 'line' as const,
 smooth: true,
 areaStyle: {
 color: {
 type: 'linear' as const,
 x: 0,
 y: 0,
 x2: 0,
 y2: 1,
 colorStops: [
 { offset: 0, color: 'rgba(16, 185, 129, 0.8)' },
 { offset: 1, color: 'rgba(20, 184, 166, 0.1)' },
 ],
 },
 },
 lineStyle: { color: '#10b981', width: 2 },
 itemStyle: { color: '#10b981' },
 data: points.map(p => p.completed),
 },
 {
 name: '失败',
 type: 'line' as const,
 smooth: true,
 areaStyle: {
 color: {
 type: 'linear' as const,
 x: 0,
 y: 0,
 x2: 0,
 y2: 1,
 colorStops: [
 { offset: 0, color: 'rgba(245, 158, 11, 0.8)' },
 { offset: 1, color: 'rgba(249, 115, 22, 0.1)' },
 ],
 },
 },
 lineStyle: { color: '#f59e0b', width: 2 },
 itemStyle: { color: '#f59e0b' },
 data: points.map(p => p.failed),
 },
 ],
 }
})
</script>
<template>
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl transition-all duration-200 hover:shadow-lg hover:border-primary/30">
 <h3 class="text-sm font-medium text-muted-foreground mb-4">
 成功/失败趋势
 </h3>
 <Skeleton v-if="isLoading" class="h-[300px] w-full" />
 <div v-else-if="!data?.length" class="h-[300px] flex items-center justify-center text-muted-foreground">
 暂无执行数据
 </div>
 <VChart v-else:option="chartOption" style="height: 300px" autoresize />
 </div>
</template>
