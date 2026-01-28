<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Clock, Play, Webhook } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
function getIcon(type: string) {
 switch (type) {
 case 'manual_trigger': return Play
 case 'webhook_trigger': return Webhook
 case 'schedule_trigger': return Clock
 default: return Play
 }
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="getIcon(props.data?.node_type || 'manual_trigger')"
 badge="触发器"
 badge-color="blue"
 >
 <div class="space-y-1">
 <div v-if="props.data?.config?.schedule" class="font-mono text-[10px] bg-secondary px-1.5 py-0.5 rounded inline-block">
 {{ props.data.config.schedule }}
 </div>
 <div v-if="props.data?.config?.path" class="font-mono text-[10px] bg-secondary px-1.5 py-0.5 rounded inline-block">
 POST {{ props.data.config.path }}
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '手动触发工作流执行' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
