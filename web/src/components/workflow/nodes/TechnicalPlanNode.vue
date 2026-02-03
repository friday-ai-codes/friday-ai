<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { FileCode } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 生成模式中文映射
const generationModeLabels: Record<string, string> = {
 full: '完整生成',
 outline_first: '先生成大纲',
}
function getGenerationModeLabel(mode: string): string {
 return generationModeLabels[mode] || mode
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="FileCode"
 badge="AI 技术方案"
 badge-color="green"
 theme="ai"
 >
 <div class="space-y-1">
 <!-- 显示生成模式 -->
 <div class="flex items-center gap-1">
 <div v-if="props.data?.config?.generation_mode" class="font-mono text-[10px] bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded">
 {{ getGenerationModeLabel(props.data.config.generation_mode) }}
 </div>
 <div v-if="props.data?.config?.max_tasks" class="text-[10px] bg-secondary px-1.5 py-0.5 rounded">
 最多 {{ props.data.config.max_tasks }} 个任务
 </div>
 </div>
 <!-- 显示功能开关 -->
 <div class="flex flex-wrap gap-1 text-[10px]">
 <span v-if="props.data?.config?.include_file_details" class="text-green-600 dark:text-green-400">
 + 文件详情
 </span>
 <span v-if="props.data?.config?.auto_transition_status" class="text-blue-600 dark:text-blue-400">
 + 自动流转
 </span>
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '根据需求生成技术方案' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
