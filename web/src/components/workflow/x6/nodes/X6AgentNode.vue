<script setup lang="ts">
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6AgentNode - AI Agent node with special styling.
 *
 * Per CONTEXT.md:
 * - Larger size to highlight AI Agent importance (px-5 py-4, icon)
 * - Robot/AI icon (bot icon) with blue-cyan gradient
 * - Orange border + pulse animation when suspended (waiting_event)
 * - Gray border + "已超时" label when timeout
 * - Status indicators for waiting_event and timeout states
 */
</script>
<template>
 <X6BaseNode v-slot="{ label, description, shortId, nodeData }">
 <div
 class="flex items-center gap-3 px-5 py-4":class="{
 'animate-pulse': nodeData.status === 'waiting_event',
 }"
 >
 <!-- Icon with AI gradient background (larger) -->
 <div class="shrink-0 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-400/10">
 <span class="icon-[lucide--bot] text-xl text-blue-500" />
 </div>
 <!-- Title + description + status -->
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2">
 <span class="font-medium text-sm truncate":title="label">
 {{ label }}
 </span>
 <!-- Status indicator: Suspended -->
 <span
 v-if="nodeData.status === 'waiting_event'"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-500 shrink-0"
 >
 挂起中
 </span>
 <!-- Status indicator: Timeout -->
 <span
 v-else-if="nodeData.status === 'timeout'"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0"
 >
 已超时
 </span>
 </div>
 <div
 v-if="description"
 class="text-xs text-muted-foreground truncate mt-0.5":title="description"
 >
 {{ description }}
 </div>
 <div class="text-[10px] text-muted-foreground/60 font-mono mt-0.5">
 {{ shortId }}
 </div>
 </div>
 </div>
 </X6BaseNode>
</template>
<style scoped>
/* Suspended state border - orange glow */:deep(.x6-node.status-waiting_event) {
 border-color: rgb(245 158 11) !important;
 box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.3);
}
/* Timeout state - gray and faded */:deep(.x6-node.status-timeout) {
 border-color: rgb(156 163 175) !important;
 opacity: 0.7;
}
</style>
