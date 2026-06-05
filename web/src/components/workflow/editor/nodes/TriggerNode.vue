<script setup lang="ts">
import { Zap } from 'lucide-vue-next'
import BaseWorkflowNode from './BaseWorkflowNode.vue'

defineProps<{
  id: string
  data: {
    name: string
    nodeType: string
    description?: string
    disabled?: boolean
    [key: string]: unknown
  }
  selected?: boolean
}>()
</script>

<template>
  <BaseWorkflowNode :id="id" :data="data" :selected="selected">
    <template #icon>
      <Zap class="w-4 h-4" />
    </template>
    <template v-if="data.description" #content>
      <p class="text-xs text-muted-foreground">
        {{ data.description }}
      </p>
    </template>
  </BaseWorkflowNode>
</template>
