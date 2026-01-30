<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { SearchCode } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
function getTopK: number {
 return props.data?.config?.top_k ?? 10
}
function getThreshold: number {
 return props.data?.config?.score_threshold ?? 0.5
}
function hasQuery: boolean {
 return !!props.data?.config?.query
}
function hasRepository: boolean {
 return !!props.data?.config?.repository_id
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="SearchCode"
 badge="RAG"
 badge-color="purple"
 theme="ai"
 >
 <div class="space-y-1">
 <!-- 显示配置状态 -->
 <div class="flex items-center gap-1 flex-wrap">
 <div
 v-if="hasRepository"
 class="font-mono text-[10px] bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded"
 >
 已配置仓库
 </div>
 <div
 v-else
 class="font-mono text-[10px] bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 px-1.5 py-0.5 rounded"
 >
 未配置仓库
 </div>
 <div class="text-[10px] bg-secondary px-1.5 py-0.5 rounded">
 Top {{ getTopK }}
 </div>
 <div class="text-[10px] bg-secondary px-1.5 py-0.5 rounded">
 阈值 {{ getThreshold }}
 </div>
 </div>
 <!-- 查询预览 -->
 <p v-if="hasQuery" class="text-[10px] text-muted-foreground truncate max-w-[180px]">
 {{ props.data?.config?.query }}
 </p>
 <p v-else class="text-[10px] text-muted-foreground">
 {{ props.data?.description || '从代码库检索相关上下文' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
