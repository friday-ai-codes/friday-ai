<script setup lang="ts">
import { Terminal, Globe, GitBranch } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
import type { NodeProps } from '@vue-flow/core'
const props = defineProps<NodeProps>
const getIcon = (type: string) => {
 switch (type) {
 case 'http_request': return Globe
 case 'code_implement': return Terminal
 case 'create_branch': return GitBranch
 default: return Terminal
 }
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="getIcon(props.data.node_type)"
 badge="Action"
 >
 <div class="space-y-1">
 <div v-if="props.data.config?.url" class="font-mono text-[10px] truncate max-w-full bg-muted px-1 rounded">
 {{ props.data.config.method || 'GET' }} {{ props.data.config.url }}
 </div>
 <p class="line-clamp-2">{{ props.data.description }}</p>
 </div>
 </BaseNodeComponent>
</template>
