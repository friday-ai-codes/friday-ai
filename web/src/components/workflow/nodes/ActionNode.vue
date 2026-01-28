<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { GitBranch, Globe, Terminal } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
function getIcon(type: string) {
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
 v-bind="props":icon="getIcon(props.data?.node_type || '')"
 badge="操作"
 badge-color="green"
 >
 <div class="space-y-1">
 <div v-if="props.data?.config?.url" class="font-mono text-[10px] truncate max-w-full bg-secondary px-1.5 py-0.5 rounded">
 {{ props.data.config.method || 'GET' }} {{ props.data.config.url }}
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '执行操作' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
