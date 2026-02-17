<script setup lang="ts">
import type { NodePaletteItemData } from '~/components/workflow/sidebar/NodePaletteItem.vue'
import { ref } from 'vue'
import NodePalette from '~/components/workflow/sidebar/NodePalette.vue'
import { X6WorkflowCanvas } from '~/components/workflow/x6'
const canvasRef = ref<InstanceType<typeof X6WorkflowCanvas>>
function handleDragStart(nodeData: NodePaletteItemData, event: MouseEvent) {
 canvasRef.value?.startDrag({
 shape: nodeData.type,
 width: 200,
 height: 80,
 data: {
 node_type: nodeData.type,
 name: nodeData.name,
 description: nodeData.description,
 },
 }, event)
}
</script>
<template>
 <div class="w-screen h-screen bg-background flex">
 <!-- Sidebar with NodePalette -->
 <div class="w-80 h-full border-r border-border/50 overflow-y-auto ">
 <NodePalette @drag-start="handleDragStart" />
 </div>
 <!-- Main Canvas Area -->
 <div class="flex-1 relative">
 <!-- Header -->
 <div class="absolute top-4 left-4 z-10 rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50">
 <h1 class="text-lg font-semibold">
 X6 Canvas Test
 </h1>
 <p class="text-sm text-muted-foreground">
 Drag to pan, Ctrl/Cmd + scroll to zoom
 </p>
 </div>
 <!-- X6 Canvas -->
 <X6WorkflowCanvas ref="canvasRef" />
 </div>
 </div>
</template>
