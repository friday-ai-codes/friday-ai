<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Sparkles } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 获取已配置的变量数量
function getVariableCount: number {
 return props.data?.config?.variables?.length ?? 0
}
// 模型简称映射
const modelShortNames: Record<string, string> = {
 'claude-sonnet-4-20250514': 'Sonnet 4',
 'claude-3-7-sonnet-20250219': 'Sonnet 3.7',
 'claude-3-5-sonnet-20241022': 'Sonnet 3.5',
 'gpt-4o': 'GPT-4o',
}
function getModelShortName(model: string): string {
 return modelShortNames[model] || model.split('-').slice(-1)[0] || model
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="Sparkles"
 badge="AI"
 badge-color="violet"
 theme="ai"
 >
 <div class="space-y-1">
 <!-- 显示模型和变量数量 -->
 <div class="flex items-center gap-1">
 <div v-if="props.data?.config?.model" class="font-mono text-[10px] bg-violet-100 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400 px-1.5 py-0.5 rounded">
 {{ getModelShortName(props.data.config.model) }}
 </div>
 <div v-if="getVariableCount > 0" class="text-[10px] bg-secondary px-1.5 py-0.5 rounded">
 {{ getVariableCount }} 个变量
 </div>
 </div>
 <!-- 显示变量列表预览 -->
 <div v-if="props.data?.config?.variables?.length" class="flex flex-wrap gap-1">
 <span
 v-for="(variable, index) in props.data.config.variables.slice(0, 3)":key="index"
 class="text-[10px] bg-secondary px-1.5 py-0.5 rounded"
 >
 {{ variable.name || variable.key }}
 </span>
 <span v-if="props.data.config.variables.length > 3" class="text-[10px] text-muted-foreground">
 +{{ props.data.config.variables.length - 3 }}
 </span>
 </div>
 <p v-else class="text-[10px] text-muted-foreground">
 {{ props.data?.description || '使用 AI 智能提取变量' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
