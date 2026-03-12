<script setup lang="ts">
import { provide, ref } from 'vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import KpiCards from '~/components/analytics/KpiCards.vue'
import TimeRangeSelector from '~/components/analytics/TimeRangeSelector.vue'
function getDateString(daysAgo: number): string {
 const d = new Date
 d.setDate(d.getDate - daysAgo)
 return d.toISOString.split('T')[0]
}
const dateRange = ref({
 from: getDateString(7),
 to: getDateString(0),
})
// 通过 provide 让所有子组件共享时间范围
provide('analyticsDateRange', dateRange)
</script>
<template>
 <PageContainer>
 <!-- 页头 -->
 <div class="flex items-center justify-between mb-6">
 <div>
 <h1 class="text-2xl font-bold bg-gradient-to-r from-primary to-primary/70 bg-clip-text text-transparent">
 执行分析
 </h1>
 <p class="text-sm text-muted-foreground mt-1">
 工作流执行健康状况、性能趋势和成本消耗
 </p>
 </div>
 <TimeRangeSelector v-model="dateRange" />
 </div>
 <!-- KPI 概览 -->
 <KpiCards class="mb-6" />
 <!-- 趋势和分布图 -->
 <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
 <!-- TrendChart 占位 — Plan 实现 -->
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl h-[360px] flex items-center justify-center text-muted-foreground">
 <span class="icon-[lucide--trending-up] text-2xl mr-2" />
 成功/失败趋势
 </div>
 <!-- DurationDistribution 占位 — Plan 实现 -->
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl h-[360px] flex items-center justify-center text-muted-foreground">
 <span class="icon-[lucide--bar-chart] text-2xl mr-2" />
 执行时长分布
 </div>
 </div>
 <!-- Token 成本和节点性能 -->
 <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
 <!-- TokenCostChart 占位 — Plan 实现 -->
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl h-[360px] flex items-center justify-center text-muted-foreground">
 <span class="icon-[lucide--coins] text-2xl mr-2" />
 Token / 成本统计
 </div>
 <!-- NodePerformanceTable 占位 — Plan 实现 -->
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl h-[360px] flex items-center justify-center text-muted-foreground">
 <span class="icon-[lucide--table] text-2xl mr-2" />
 节点性能排行
 </div>
 </div>
 </PageContainer>
</template>
