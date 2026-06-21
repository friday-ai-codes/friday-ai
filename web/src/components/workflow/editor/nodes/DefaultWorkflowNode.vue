<script setup lang="ts">
import type { NodeCategory } from '~/types/workflow/registry'
/**
 * DefaultWorkflowNode - 临时基础节点组件
 *
 * 所有 27 种节点类型共用此组件， 会替换为完整自定义节点。
 * 使用 Vue Flow 的 NodeProps 接收节点数据，按类别显示不同边框色。
 */
import { Handle, Position } from '@vue-flow/core'
import { computed } from 'vue'

const props = defineProps<{
  id: string
  data: {
    name: string
    nodeType: string
    category?: NodeCategory
  }
}>()

/** 按节点类别映射边框色 */
const categoryBorderClass = computed(() => {
  const map: Record<string, string> = {
    trigger: 'border-primary/50',
    action: 'border-violet-500/50',
    control: 'border-amber-500/50',
    integration: 'border-emerald-500/50',
    ai: 'border-violet-500/50',
  }
  return map[props.data.category ?? ''] ?? 'border-border/50'
})
</script>

<template>
  <div
    class="w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl px-3 py-2 shadow-sm"
    :class="categoryBorderClass"
  >
    <Handle id="default" type="target" :position="Position.Left" />

    <div class="text-sm font-medium truncate">
      {{ data.name }}
    </div>
    <div class="text-xs text-muted-foreground truncate">
      {{ data.nodeType }}
    </div>

    <Handle id="default" type="source" :position="Position.Right" />
  </div>
</template>
