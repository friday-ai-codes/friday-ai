<script setup lang="ts">
import { Clock, Settings } from 'lucide-vue-next'
import { computed, type Component } from 'vue'
import BaseWorkflowNode from './BaseWorkflowNode.vue'
const props = defineProps<{
 id: string
 data: {
 name: string
 nodeType: string
 description?: string
 disabled?: boolean
 [key: string]: unknown
 }
 selected?: boolean
}>
const iconMap: Record<string, Component> = {
 wait_feishu_field: Clock,
}
const icon = computed( => iconMap[props.data.nodeType] ?? Settings)
</script>
<template>
 <BaseWorkflowNode:id="id":data="data":selected="selected">
 <template #icon>
 <component:is="icon" class="w-4 " />
 </template>
 <template v-if="data.description" #content>
 <p class="text-xs text-muted-foreground">{{ data.description }}</p>
 </template>
 </BaseWorkflowNode>
</template>
