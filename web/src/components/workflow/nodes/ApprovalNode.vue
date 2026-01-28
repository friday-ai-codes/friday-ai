<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { MessageSquare } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="MessageSquare"
 badge="审批"
 badge-color="orange"
 >
 <div class="space-y-1">
 <div class="flex items-center gap-1 text-[10px]">
 <span class="opacity-70">审批人:</span>
 <span class="font-medium">{{ props.data?.config?.approvers?.length || '任意' }}</span>
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '等待人工审批' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
