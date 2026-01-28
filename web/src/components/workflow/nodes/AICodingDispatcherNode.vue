<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { GitBranch } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 粒度中文映射
const granularityLabels: Record<string, string> = {
 fine: '细粒度',
 medium: '中粒度',
 coarse: '粗粒度',
}
function getGranularityLabel(granularity: string): string {
 return granularityLabels[granularity] || granularity
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="GitBranch"
 badge="AI 编码"
 badge-color="purple"
 theme="ai"
 >
 <div class="space-y-1">
 <!-- 显示最大任务数 -->
 <div class="flex items-center gap-1">
 <div v-if="props.data?.config?.max_tasks" class="font-mono text-[10px] bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 px-1.5 py-0.5 rounded">
 最多 {{ props.data.config.max_tasks }} 个任务
 </div>
 <div v-if="props.data?.config?.task_granularity" class="text-[10px] bg-secondary px-1.5 py-0.5 rounded">
 {{ getGranularityLabel(props.data.config.task_granularity) }}
 </div>
 </div>
 <!-- 显示功能开关 -->
 <div class="flex flex-wrap gap-1 text-[10px]">
 <span v-if="props.data?.config?.include_tests" class="text-green-600 dark:text-green-400">
 ✓ 含测试
 </span>
 <span v-if="props.data?.config?.auto_assign_repos" class="text-blue-600 dark:text-blue-400">
 ✓ 自动分配
 </span>
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '分析需求并分配编码任务' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
