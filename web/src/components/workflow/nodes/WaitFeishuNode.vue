<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Clock } from 'lucide-vue-next'
import { computed } from 'vue'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 从条件配置生成摘要文本
const conditionSummary = computed( => {
 const condition = props.data?.config?.condition
 if (!condition || !condition.conditions || condition.conditions.length === 0) {
 return '点击配置条件'
 }
 const conditions = condition.conditions as Array<{
 field: string
 operator: string
 value: string
 }>
 const logic = condition.logic === 'or' ? ' 或 ': ' 且 '
 const operatorLabels: Record<string, string> = {
 eq: '=',
 ne: '!=',
 gt: '>',
 gte: '>=',
 lt: '<',
 lte: '<=',
 contains: '包含',
 not_contains: '不包含',
 is_empty: '为空',
 is_not_empty: '不为空',
 regex: '匹配',
 }
 const parts = conditions.slice(0, 2).map((c) => {
 const op = operatorLabels[c.operator] || c.operator
 if (c.operator === 'is_empty' || c.operator === 'is_not_empty') {
 return `${c.field} ${op}`
 }
 return `${c.field} ${op} ${c.value}`
 })
 if (conditions.length > 2) {
 parts.push(`+${conditions.length - 2}`)
 }
 return parts.join(logic)
})
// 超时配置显示
const timeoutDisplay = computed( => {
 const seconds = props.data?.config?.timeout_seconds
 if (seconds === -1) return '不超时'
 if (!seconds || seconds === 0) return '7 天'
 if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
 if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时`
 return `${Math.round(seconds / 86400)} 天`
})
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="Clock"
 badge="等待"
 badge-color="orange"
 >
 <div class="space-y-1.5">
 <div class="flex items-center gap-1 text-[10px]">
 <span class="opacity-70">等待:</span>
 <span class="font-medium text-amber-600 dark:text-amber-400">
 {{ conditionSummary }}
 </span>
 </div>
 <div class="flex items-center gap-2 text-[10px] text-muted-foreground">
 <span>超时: {{ timeoutDisplay }}</span>
 </div>
 </div>
 </BaseNodeComponent>
</template>
