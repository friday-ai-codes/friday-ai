<script setup lang="ts">
import { computed } from 'vue'
import { usePaletteDragState } from '../editor/composables/usePaletteDragState'
import { getNodeVisual } from '../editor/nodes/nodeVisuals'

const props = defineProps<{
  nodeType: string
  name: string
  description: string
}>()

const visual = computed(() => getNodeVisual(props.nodeType))
const { startPaletteDrag, endPaletteDrag } = usePaletteDragState()

function handleDragStart(event: DragEvent) {
  event.dataTransfer?.setData('application/vueflow', props.nodeType)
  event.dataTransfer?.setData('application/vueflow-name', props.name)
  event.dataTransfer!.effectAllowed = 'move'
  // SLOT-04：记录被拖能力，供宿主节点能力槽在 dragover 期判定类型匹配高亮。
  startPaletteDrag(props.nodeType)
}

function handleDragEnd() {
  endPaletteDrag()
}

function getIconGradient(color: string): string {
  const gradients: Record<string, string> = {
    blue: 'bg-primary/10',
    green: 'bg-primary/10',
    purple: 'bg-primary/10',
    orange: 'bg-primary/10',
  }
  return gradients[color] || gradients.blue
}

function getIconColor(color: string): string {
  const colors: Record<string, string> = {
    blue: 'text-primary',
    green: 'text-primary',
    purple: 'text-primary',
    orange: 'text-primary',
  }
  return colors[color] || colors.blue
}

function getHoverGlow(color: string): string {
  const glows: Record<string, string> = {
    blue: 'group-hover:shadow-primary/10 group-hover:border-primary/30',
    green: 'group-hover:shadow-primary/10 group-hover:border-primary/30',
    purple: 'group-hover:shadow-primary/10 group-hover:border-primary/30',
    orange: 'group-hover:shadow-primary/10 group-hover:border-primary/30',
  }
  return glows[color] || glows.blue
}
</script>

<template>
  <div
    draggable="true"
    class="group flex items-center gap-3 p-3 text-sm rounded-xl bg-card/70 backdrop-blur-sm border border-border/50 transition-all duration-300 cursor-grab active:cursor-grabbing hover:bg-card/90 hover:shadow-md"
    :class="getHoverGlow(visual.color)"
    @dragstart="handleDragStart"
    @dragend="handleDragEnd"
  >
    <!-- Drag Handle (6-dot grip) -->
    <div
      class="p-1.5 rounded-lg bg-muted/50 hover:bg-muted transition-colors duration-200"
    >
      <span class="icon-[lucide--grip-vertical] text-lg text-muted-foreground" />
    </div>

    <!-- Node Icon -->
    <div
      class="p-2 rounded-lg transition-transform duration-200 group-hover:scale-105"
      :class="getIconGradient(visual.color)"
    >
      <component :is="visual.icon" class="w-4 h-4" :class="getIconColor(visual.color)" />
    </div>

    <!-- Node Info -->
    <div class="flex-1 min-w-0">
      <div class="font-medium text-foreground text-sm leading-tight">
        {{ name }}
      </div>
      <div class="text-[10px] text-muted-foreground truncate mt-0.5">
        {{ description }}
      </div>
    </div>

    <!-- Arrow indicator on hover -->
    <div class="opacity-0 group-hover:opacity-100 transition-opacity duration-200">
      <span
        class="icon-[lucide--arrow-right] text-sm text-muted-foreground/60 group-hover:translate-x-1 transition-transform duration-200"
      />
    </div>
  </div>
</template>
