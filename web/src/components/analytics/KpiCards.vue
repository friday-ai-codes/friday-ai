<script setup lang="ts">
/**
 * Analytics KPI 卡片（Phase Plan — ）
 *
 * 两种渲染模式：
 * - grouping === 'none'：4 张原始 KPI（执行总数 / 成功率 / 平均时长 / 总成本）
 * - grouping === 'provider_type'：按 Provider 展开为每 Provider 一张成本卡 + 底部汇总行
 */
import type { Ref } from 'vue'
import type { AnalyticsGrouping } from '~/stores/analyticsFilters'
import type { ProviderType } from '~/types/providerCredential'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject } from 'vue'
import api from '~/api/client'
import { Skeleton } from '~/components/ui/skeleton'
import { getProviderBrandColor } from '~/lib/providerBrandColors'
interface OverviewFlat {
 total_executions: number
 success_rate: number
 avg_duration_seconds: number | null
 total_cost_usd: number
}
interface OverviewGrouped {
 group_by: 'none' | 'provider_type' | 'project'
 groups?: Record<string, { total_tokens: number, total_cost_usd: number, count: number }>
 total?: OverviewFlat
}
interface Props {
 grouping?: AnalyticsGrouping
}
const props = withDefaults(defineProps<Props>, { grouping: 'none' })
const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!
const queryParams = computed( => ({
 date_from: dateRange.value.from,
 date_to: dateRange.value.to,
}))
const groupingRef = computed( => props.grouping)
const { data, isLoading } = useQuery({
 queryKey: ['analytics-overview', queryParams, groupingRef],
 queryFn: async => {
 // grouping='none' 时不带 group_by 参数（命中 legacy flat shape 兼容路径）
 if (groupingRef.value === 'none')
 return await api.get<OverviewFlat>('/analytics/overview/', queryParams.value)
 return await api.get<OverviewGrouped>('/analytics/overview/', {
 ...queryParams.value,
 group_by: groupingRef.value,
 })
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
function formatTokens(n: number): string {
 if (n >= 1e6)
 return `${(n / 1e6).toFixed(2)}M`
 if (n >= 1e3)
 return `${(n / 1e3).toFixed(1)}K`
 return n.toLocaleString
}
// ---- 不分组：4 张原始 KPI ----
const flatKpis = computed( => {
 const flat = (data.value && 'total_executions' in data.value)
 ? data.value as OverviewFlat: ((data.value as OverviewGrouped | undefined)?.total)
 return [
 {
 label: '执行总数',
 value: flat?.total_executions ?? '—',
 icon: 'lucide--play-circle',
 bgGradient: 'from-primary/20 to-primary/10',
 },
 {
 label: '成功率',
 value: flat ? `${flat.success_rate.toFixed(1)}%`: '—',
 icon: 'lucide--check-circle-2',
 bgGradient: 'from-primary/20 to-primary/10',
 },
 {
 label: '平均时长',
 value: flat ? formatDuration(flat.avg_duration_seconds): '—',
 icon: 'lucide--clock',
 bgGradient: 'from-primary/20 to-primary/10',
 },
 {
 label: '总成本',
 value: flat ? formatCost(flat.total_cost_usd): '—',
 icon: 'lucide--dollar-sign',
 bgGradient: 'from-primary/20 to-primary/10',
 },
 ]
})
// ---- 按 Provider 分组：每 Provider 一张卡片 + 汇总行 ----
const providerCards = computed( => {
 if (props.grouping !== 'provider_type')
 return
 const grouped = data.value as OverviewGrouped | undefined
 if (!grouped?.groups)
 return
 // 字典序
 const ordered: (ProviderType | 'unknown') = [
 'anthropic',
 'gemini',
 'ollama',
 'openai_chat',
 'openai_responses',
 'unknown',
 ]
 return ordered
 .filter(pt => grouped.groups?.[pt])
 .map((pt) => {
 const g = grouped.groups![pt]
 const color = getProviderBrandColor(pt === 'unknown' ? null: pt)
 // Provider 中文名
 const labelMap: Record<string, string> = {
 anthropic: 'Anthropic',
 openai_chat: 'OpenAI（Chat）',
 openai_responses: 'OpenAI（Responses）',
 gemini: 'Gemini',
 ollama: 'Ollama',
 unknown: '未知',
 }
 return {
 providerType: pt,
 label: labelMap[pt] ?? pt,
 tokens: g.total_tokens,
 cost: g.total_cost_usd,
 count: g.count,
 bg: color.bg,
 text: color.text,
 }
 })
})
const totalSummary = computed( => {
 const grouped = data.value as OverviewGrouped | undefined
 return grouped?.total ?? null
})
</script>
<template>
 <!-- 不分组：4 张原始 KPI -->
 <div v-if="grouping === 'none'" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
 <div
 v-for="kpi in flatKpis":key="kpi.label"
 class="group card transition-all duration-200 hover:shadow-lg hover:border-primary/30"
 >
 <div class="flex items-center gap-4">
 <div class="bg-linear-to-br rounded-lg .5":class="[kpi.bgGradient]">
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
 <p class="text-2xl font-bold font-mono">
 {{ kpi.value }}
 </p>
 </template>
 <Skeleton v-else class=" w-20 mt-1" />
 </div>
 </div>
 </div>
 </div>
 <!-- 按 Provider：每 Provider 一张卡片 + 汇总行 -->
 <div v-else-if="grouping === 'provider_type'" class="space-y-4">
 <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
 <div
 v-for="card in providerCards":key="card.providerType"
 class="group card transition-all duration-200 hover:shadow-lg hover:border-primary/30"
 >
 <div class="flex items-center gap-4">
 <div class="rounded-lg .5":class="[card.bg]">
 <span class="text-xl icon-[lucide--cpu]":class="[card.text]" />
 </div>
 <div class="flex-1 min-w-0">
 <p class="text-sm text-muted-foreground">
 {{ card.label }}
 </p>
 <p class="text-2xl font-bold font-mono">
 {{ formatCost(card.cost) }}
 </p>
 <p class="text-xs text-muted-foreground font-mono">
 {{ formatTokens(card.tokens) }} tokens · {{ card.count }} 次
 </p>
 </div>
 </div>
 </div>
 <!-- Provider 无数据时的空态 -->
 <div
 v-if="providerCards.length === 0 && !isLoading"
 class="col-span-full card text-center text-muted-foreground"
 >
 当前时段内无任何 Provider 成本记录
 </div>
 </div>
 <!-- 底部汇总行 -->
 <div
 v-if="totalSummary"
 class="card ring-1 ring-primary/30"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <span class="icon-[lucide--layers] text-xl text-primary" />
 <span class="text-sm font-semibold text-primary">全 Provider 汇总</span>
 </div>
 <div class="flex items-center gap-6 text-sm font-mono">
 <span>执行 {{ totalSummary.total_executions }}</span>
 <span>成功率 {{ totalSummary.success_rate.toFixed(1) }}%</span>
 <span class="font-bold">{{ formatCost(totalSummary.total_cost_usd) }}</span>
 </div>
 </div>
 </div>
 </div>
 <!-- 按项目：暂用汇总 fallback（后续 Plan 可扩展 project-level cards） -->
 <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
 <div
 v-for="kpi in flatKpis":key="kpi.label"
 class="group card transition-all duration-200 hover:shadow-lg hover:border-primary/30"
 >
 <div class="flex items-center gap-4">
 <div class="bg-linear-to-br rounded-lg .5":class="[kpi.bgGradient]">
 <span
 v-if="!isLoading"
 class="text-xl":class="[`icon-[${kpi.icon}]`]"
 />
 <Skeleton v-else class=" w-5" />
 </div>
 <div class="flex-1 min-w-0">
 <p class="text-sm text-muted-foreground">
 {{ kpi.label }}（按项目）
 </p>
 <template v-if="!isLoading">
 <p class="text-2xl font-bold font-mono">
 {{ kpi.value }}
 </p>
 </template>
 <Skeleton v-else class=" w-20 mt-1" />
 </div>
 </div>
 </div>
 </div>
</template>
