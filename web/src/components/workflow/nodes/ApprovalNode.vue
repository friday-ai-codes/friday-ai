<script setup lang="ts">
import { MessageSquare } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
import type { NodeProps } from '@vue-flow/core'
const props = defineProps<NodeProps>
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="MessageSquare"
 badge="Approval"
 class="border- border-l-orange-500"
 >
 <div class="space-y-1">
 <div class="flex items-center gap-1 text-[10px] text-muted-foreground">
 <span>Approvers:</span>
 <span class="font-medium text-foreground">{{ props.data.config?.approvers?.length || 'Any' }}</span>
 </div>
 <p class="line-clamp-2">{{ props.data.description || 'Waits for human approval' }}</p>
 </div>
 </BaseNodeComponent>
</template>
