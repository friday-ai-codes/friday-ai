<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Webhook } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 事件类型中文映射
const eventTypeLabels: Record<string, string> = {
 WorkitemCreateEvent: '工作项创建',
 WorkitemStatusEvent: '状态变更',
 WorkitemCommentEvent: '评论事件',
 WorkitemUpdateEvent: '字段更新',
 WorkFlowNodeStatusEvent: '节点流转',
}
function getEventTypeLabel(type: string): string {
 return eventTypeLabels[type] || type
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="Webhook"
 badge="飞书触发"
 badge-color="blue"
 theme="feishu"
 >
 <div class="space-y-1">
 <!-- 显示已配置的事件类型 -->
 <div v-if="props.data?.config?.event_types?.length" class="flex flex-wrap gap-1">
 <div
 v-for="eventType in props.data.config.event_types.slice(0, 2)":key="eventType"
 class="font-mono text-[10px] bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded"
 >
 {{ getEventTypeLabel(eventType) }}
 </div>
 <div
 v-if="props.data.config.event_types.length > 2"
 class="font-mono text-[10px] bg-secondary px-1.5 py-0.5 rounded"
 >
 +{{ props.data.config.event_types.length - 2 }}
 </div>
 </div>
 <!-- 显示过滤条件 -->
 <div v-if="props.data?.config?.filter_project_key" class="font-mono text-[10px] bg-secondary px-1.5 py-0.5 rounded inline-block">
 项目: {{ props.data.config.filter_project_key }}
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '监听飞书工作项事件' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
