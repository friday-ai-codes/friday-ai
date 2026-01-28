<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { MessageSquare } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 模型简称映射
const modelShortNames: Record<string, string> = {
 'claude-3-opus-20240229': 'Opus',
 'claude-3-sonnet-20240229': 'Sonnet',
 'claude-3-5-sonnet-20241022': 'Sonnet 3.5',
 'gpt-4': '',
 'gpt-4-turbo': ' Turbo',
 'gpt-3.5-turbo': '.5',
}
function getModelShortName(model: string): string {
 return modelShortNames[model] || model.split('-').slice(-1)[0] || model
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="MessageSquare"
 badge="AI"
 badge-color="purple"
 theme="ai"
 >
 <div class="space-y-1">
 <!-- 显示模型信息 -->
 <div v-if="props.data?.config?.model" class="flex items-center gap-1">
 <div class="font-mono text-[10px] bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 px-1.5 py-0.5 rounded">
 {{ getModelShortName(props.data.config.model) }}
 </div>
 <div v-if="props.data?.config?.temperature !== undefined" class="text-[10px] text-muted-foreground">
 T={{ props.data.config.temperature }}
 </div>
 </div>
 <!-- 显示输出格式 -->
 <div v-if="props.data?.config?.output_format && props.data.config.output_format !== 'text'" class="text-[10px] bg-secondary px-1.5 py-0.5 rounded inline-block">
 输出: {{ props.data.config.output_format.toUpperCase }}
 </div>
 <!-- 显示 Prompt 预览 -->
 <p v-if="props.data?.config?.user_prompt" class="line-clamp-2 text-[10px] text-muted-foreground font-mono">
 {{ props.data.config.user_prompt.substring(0, 50) }}{{ props.data.config.user_prompt.length > 50 ? '...': '' }}
 </p>
 <p v-else class="line-clamp-2">
 {{ props.data?.description || '调用 AI 大语言模型' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
