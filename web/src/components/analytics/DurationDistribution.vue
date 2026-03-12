<script setup lang="ts">
import { computed, inject, type Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import api from '~/api/client'
import { VChart } from '~/components/analytics/echarts-setup'
import { Skeleton } from '~/components/ui/skeleton'
interface DurationBucket {
 bucket_label: string
 count: number
}
const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!
const queryParams = computed( => ({
 date_from: dateRange.value.from,
 date_to: dateRange.value.to,
}))
const { data, isLoading } = useQuery({
 queryKey: ['analytics-duration-distribution', queryParams],
 queryFn: async => {
 return await api.get<DurationBucket>('/analytics/duration-distribution/', queryParams.value)
 },
 placeholderData: keepPreviousData,
})
const chartOption = computed( => {
 const buckets = data.value ||
 return {
 tooltip: {
 trigger: 'axis' as const,
 backgroundColor: 'rgba(17, 24, 39, 0.9)',
 borderColor: 'rgba(75, 85, 99, 0.3)',
 textStyle: { color: '#e5e7eb' },
 },
 grid: {
 left: '3%',
 right: '4%',
 bottom: '3%',
 containLabel: true,
 },
 xAxis: {
 type: 'category' as const,
 data: buckets.map(b => b.bucket_label),
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
 type: 'bar' as const,
 data: buckets.map(b => b.count),
 itemStyle: {
 color: {
 type: 'linear' as const,
 x: 0, y: 0, x2: 0, y2: 1,
 colorStops: [
 { offset: 0, color: '#3b82f6' },
 { offset: 1, color: '#06b6d4' },
 ],
 },
 borderRadius: [4, 4, 0, 0],
 },
 barMaxWidth: 40,
 },
 ],
 }
})
</script>
<template>
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl transition-all duration-200 hover:shadow-lg hover:border-primary/30">
 <h3 class="text-sm font-medium text-muted-foreground mb-4">执行时长分布</h3>
 <Skeleton v-if="isLoading" class="h-[300px] w-full" />
 <div v-else-if="!data?.some(b => b.count > 0)" class="h-[300px] flex items-center justify-center text-muted-foreground">
 暂无执行数据
 </div>
 <VChart v-else:option="chartOption" style="height: 300px" autoresize />
 </div>
</template>
