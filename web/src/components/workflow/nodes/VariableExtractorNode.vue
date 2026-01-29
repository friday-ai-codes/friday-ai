<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Variable } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 获取已配置的变量数量
function getVariableCount: number {
 return props.data?.config?.extractions?.length ?? 0
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="Variable"
 badge="DATA"
 badge-color="cyan"
 theme="action"
 >
 <div class="space-y-1">
 <!-- 显示变量数量 -->
 <div v-if="getVariableCount > 0" class="flex items-center gap-1">
 <div class="font-mono text-[10px] bg-cyan-100 dark:bg-cyan-900/30 text-cyan-600 dark:text-cyan-400 px-1.5 py-0.5 rounded">
 {{ getVariableCount }} 个变量
 </div>
 </div>
 <!-- 显示变量列表预览 -->
 <div v-if="props.data?.config?.extractions?.length" class="flex flex-wrap gap-1">
 <span
 v-for="(extraction, index) in props.data.config.extractions.slice(0, 3)":key="index"
 class="text-[10px] bg-secondary px-1.5 py-0.5 rounded"
 >
 {{ extraction.name || extraction.key }}
 </span>
 <span v-if="props.data.config.extractions.length > 3" class="text-[10px] text-muted-foreground">
 +{{ props.data.config.extractions.length - 3 }}
 </span>
 </div>
 <p v-else class="text-[10px] text-muted-foreground">
 {{ props.data?.description || '从 JSON 数据中提取全局变量' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
