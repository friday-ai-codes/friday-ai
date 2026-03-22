<script setup lang="ts">
import { provide, ref } from 'vue'
import DurationDistribution from '~/components/analytics/DurationDistribution.vue'
import KpiCards from '~/components/analytics/KpiCards.vue'
import NodePerformanceTable from '~/components/analytics/NodePerformanceTable.vue'
import TimeRangeSelector from '~/components/analytics/TimeRangeSelector.vue'
import TokenCostChart from '~/components/analytics/TokenCostChart.vue'
import TrendChart from '~/components/analytics/TrendChart.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
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
 <PageHeader
 icon="lucide--bar-chart-3"
 icon-gradient="from-teal-500/20 to-cyan-500/10"
 icon-color="text-teal-500"
 title="执行分析"
 description="工作流执行健康状况、性能趋势和成本消耗"
 >
 <template #actions>
 <TimeRangeSelector v-model="dateRange" />
 </template>
 </PageHeader>
 <!-- KPI 概览 -->
 <KpiCards class="mb-6" />
 <!-- 趋势和分布图 -->
 <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
 <TrendChart />
 <DurationDistribution />
 </div>
 <!-- Token 成本和节点性能 -->
 <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
 <TokenCostChart />
 <NodePerformanceTable />
 </div>
 </PageContainer>
</template>
