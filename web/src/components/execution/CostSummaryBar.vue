<script setup lang="ts">
/**
 * CostSummaryBar — DAG 画布上方的成本摘要浮层
 *
 * 显示执行级总成本（USD）和总 Token 数，glassmorphism 风格。
 */
import type { CostBreakdownSummary } from '~/types/execution'
import { Skeleton } from '~/components/ui/skeleton'
const props = defineProps<{
 costSummary: CostBreakdownSummary | null
 loading: boolean
}>
const costFormatter = new Intl.NumberFormat('en-US', {
 style: 'currency',
 currency: 'USD',
 minimumFractionDigits: 2,
 maximumFractionDigits: 4,
})
function formatCost(costUsdString: string): string {
 const val = Number.parseFloat(costUsdString)
 if (Number.isNaN(val) || val === 0) return '$0.00'
 return costFormatter.format(val)
}
function formatTokenCount(count: number): string {
 if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
 if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`
 return String(count)
}
</script>
<template>
 <!-- loading 状态 -->
 <div
 v-if="loading"
 class="flex items-center gap-3 px-3 py-1.5 bg-card/80 backdrop-blur-sm
 border border-border/50 rounded-2xl shadow-sm"
 >
 <Skeleton class=" w-16" />
 <Skeleton class=" w-20" />
 </div>
 <!-- 有数据时渲染 -->
 <div
 v-else-if="costSummary"
 class="flex items-center gap-3 px-3 py-1.5 bg-card/80 backdrop-blur-sm
 border border-border/50 rounded-2xl shadow-sm text-xs"
 >
 <!-- 总成本 -->
 <div class="flex items-center gap-1 text-foreground">
 <span class="icon-[lucide--coins] w-3.5 .5 text-amber-500" />
 <span class="font-medium tabular-nums">{{ formatCost(costSummary.total_cost_usd) }}</span>
 </div>
 <div class="w-px .5 bg-border/50" />
 <!-- 总 Token -->
 <div class="flex items-center gap-1 text-muted-foreground">
 <span class="icon-[lucide--hash] w-3.5 .5" />
 <span class="tabular-nums">{{ formatTokenCount(costSummary.total_tokens) }} tokens</span>
 </div>
 </div>
</template>
