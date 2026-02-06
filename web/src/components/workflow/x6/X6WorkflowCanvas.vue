<script setup lang="ts">
import { ref } from 'vue'
import { useGraph } from './useGraph'
/**
 * X6 Workflow Canvas Component
 *
 * Renders an X6 graph canvas with:
 * - Dot grid background for visual alignment
 * - Mouse drag to pan the canvas
 * - Ctrl/Cmd + mousewheel to zoom
 *
 * The graph instance is managed by the useGraph composable,
 * which handles lifecycle (init on mount, dispose on unmount).
 */
const containerRef = ref<HTMLDivElement>
const { graph } = useGraph(containerRef)
// Expose graph instance for parent components that need direct access
defineExpose({
 graph,
})
</script>
<template>
 <div class="relative w-full h-full overflow-hidden">
 <!-- X6 Graph container - must have explicit dimensions via parent -->
 <div
 ref="containerRef"
 class="absolute inset-0"
 />
 </div>
</template>
