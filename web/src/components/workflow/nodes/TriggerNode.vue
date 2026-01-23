<script setup lang="ts">
import { Play, Webhook, Clock } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
import type { NodeProps } from '@vue-flow/core'
const props = defineProps<NodeProps>
const getIcon = (type: string) => {
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
 v-bind="props":icon="getIcon(props.data.node_type || 'manual_trigger')"
 badge="Trigger"
 class="border- border-l-blue-500"
 >
 <div class="space-y-1">
 <div v-if="props.data.config?.schedule" class="font-mono text-[10px] bg-muted px-1 rounded inline-block">
 {{ props.data.config.schedule }}
 </div>
 <div v-if="props.data.config?.path" class="font-mono text-[10px] bg-muted px-1 rounded inline-block">
 POST {{ props.data.config.path }}
 </div>
 <p class="line-clamp-2">{{ props.data.description || 'Starts the workflow execution' }}</p>
 </div>
 </BaseNodeComponent>
</template>
