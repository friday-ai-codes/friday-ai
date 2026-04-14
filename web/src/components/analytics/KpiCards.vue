<script setup lang="ts">
import type { Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import api from '~/api/client'
import { Skeleton } from '~/components/ui/skeleton'
interface OverviewData {
 total_executions: number
 success_rate: number
 avg_duration_seconds: number | null
 total_cost_usd: number
}
const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!
const queryParams = computed( => ({
 date_from: dateRange.value.from,
 date_to: dateRange.value.to,
}))
const { data, isLoading } = useQuery({
 queryKey: ['analytics-overview', queryParams],
 queryFn: async => {
 return await api.get<OverviewData>('/analytics/overview/', queryParams.value)
 },
 placeholderData: keepPreviousData,
})
function formatDuration(seconds: number | null): string {
 if (seconds === null || seconds === undefined)
 return '—'
 if (seconds < 60)
 return `${seconds.toFixed(1)}s`
 if (seconds < 3600)
 return `${(seconds / 60).toFixed(1)}min`
 return `${(seconds / 3600).toFixed(1)}h`
}
function formatCost(usd: number): string {
 if (usd === 0)
 return '$0.00'
 if (usd < 0.01)
 return `$${usd.toFixed(4)}`
 return `$${usd.toFixed(2)}`
}
const kpis = computed( => [
 {
 label: '执行总数',
 value: data.value?.total_executions ?? '—',
 icon: 'lucide--play-circle',
 gradient: 'from-teal-500 to-cyan-400',
 bgGradient: 'from-primary/20 to-primary/10',
 },
 {
 label: '成功率',
 value: data.value ? `${data.value.success_rate.toFixed(1)}%`: '—',
 icon: 'lucide--check-circle-2',
 gradient: 'from-emerald-500 to-teal-400',
 bgGradient: 'from-emerald-500/20 to-teal-400/10',
 },
 {
 label: '平均时长',
 value: data.value ? formatDuration(data.value.avg_duration_seconds): '—',
 icon: 'lucide--clock',
 gradient: 'from-amber-500 to-orange-400',
 bgGradient: 'from-amber-500/20 to-orange-400/10',
 },
 {
 label: '总成本',
 value: data.value ? formatCost(data.value.total_cost_usd): '—',
 icon: 'lucide--dollar-sign',
 gradient: 'from-violet-500 to-purple-400',
 bgGradient: 'from-violet-500/20 to-purple-400/10',
 },
])
</script>
<template>
 <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
 <div
 v-for="kpi in kpis":key="kpi.label"
 class="group bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl transition-all duration-200 hover:shadow-lg hover:border-primary/30"
 >
 <div class="flex items-center gap-4">
 <div class="bg-gradient-to-br rounded-lg .5":class="[kpi.bgGradient]">
 <span
 v-if="!isLoading"
 class="text-xl":class="[`icon-[${kpi.icon}]`]"
 />
 <Skeleton v-else class=" w-5" />
 </div>
 <div class="flex-1 min-w-0">
 <p class="text-sm text-muted-foreground">
 {{ kpi.label }}
 </p>
 <template v-if="!isLoading">
 <p
 class="text-2xl font-bold"
 >
 {{ kpi.value }}
 </p>
 </template>
 <Skeleton v-else class=" w-20 mt-1" />
 </div>
 </div>
 </div>
 </div>
</template>
