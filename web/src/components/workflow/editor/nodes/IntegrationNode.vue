<script setup lang="ts">
import type { Component } from 'vue'
import { FileText, FolderSearch, Plug } from 'lucide-vue-next'
import { computed } from 'vue'
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
}>()

const iconMap: Record<string, Component> = {
  fetch_work_item: FileText,
  fetch_project_info: FolderSearch,
}

const icon = computed(() => iconMap[props.data.nodeType] ?? Plug)
</script>

<template>
  <BaseWorkflowNode :id="id" :data="data" :selected="selected">
    <template #icon>
      <component :is="icon" class="w-4 h-4" />
    </template>
    <template v-if="data.description" #content>
      <p class="text-xs text-muted-foreground">
        {{ data.description }}
      </p>
    </template>
  </BaseWorkflowNode>
</template>
