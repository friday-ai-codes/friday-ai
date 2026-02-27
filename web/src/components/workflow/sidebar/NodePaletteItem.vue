<script setup lang="ts">
import { computed } from 'vue'
import { getNodeVisual } from '../editor/nodes/nodeVisuals'
const props = defineProps<{
 nodeType: string
 name: string
 description: string
}>
const visual = computed( => getNodeVisual(props.nodeType))
function handleDragStart(event: DragEvent) {
 event.dataTransfer?.setData('application/vueflow', props.nodeType)
 event.dataTransfer?.setData('application/vueflow-name', props.name)
 event.dataTransfer!.effectAllowed = 'move'
}
function getIconGradient(color: string): string {
 const gradients: Record<string, string> = {
 blue: 'bg-gradient-to-br from-blue-500/20 to-cyan-400/10',
 green: 'bg-gradient-to-br from-emerald-500/20 to-teal-400/10',
 purple: 'bg-gradient-to-br from-violet-500/20 to-purple-400/10',
 orange: 'bg-gradient-to-br from-amber-500/20 to-orange-400/10',
 }
 return gradients[color] || gradients.blue
}
function getIconColor(color: string): string {
 const colors: Record<string, string> = {
 blue: 'text-blue-500',
 green: 'text-emerald-500',
 purple: 'text-violet-500',
 orange: 'text-amber-500',
 }
 return colors[color] || colors.blue
}
function getHoverGlow(color: string): string {
 const glows: Record<string, string> = {
 blue: 'group-hover:shadow-blue-500/10 group-hover:border-blue-500/30',
 green: 'group-hover:shadow-emerald-500/10 group-hover:border-emerald-500/30',
 purple: 'group-hover:shadow-violet-500/10 group-hover:border-violet-500/30',
 orange: 'group-hover:shadow-amber-500/10 group-hover:border-amber-500/30',
 }
 return glows[color] || glows.blue
}
</script>
<template>
 <div
 draggable="true"
 class="group flex items-center gap-3 text-sm rounded-xl
 bg-card/70 backdrop-blur-sm border border-border/50
 transition-all duration-300 cursor-grab active:cursor-grabbing
 hover:bg-card/90 hover:shadow-md":class="getHoverGlow(visual.color)"
 @dragstart="handleDragStart"
 >
 <!-- Drag Handle (6-dot grip) -->
 <div
 class=".5 rounded-lg bg-muted/50
 hover:bg-muted transition-colors duration-200"
 >
 <span class="icon-[lucide--grip-vertical] text-lg text-muted-foreground" />
 </div>
 <!-- Node Icon -->
 <div
 class=" rounded-lg transition-transform duration-200 group-hover:scale-105":class="getIconGradient(visual.color)"
 >
 <component:is="visual.icon" class="w-4 ":class="getIconColor(visual.color)" />
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
 class="icon-[lucide--arrow-right] text-sm text-muted-foreground/60
 group-hover:translate-x-1 transition-transform duration-200"
 />
 </div>
 </div>
</template>
