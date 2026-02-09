<script setup lang="ts">
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6AgentNode - AI Agent node with special styling and execution feedback.
 *
 * Per CONTEXT.md:
 * - Larger size to highlight AI Agent importance (px-5 py-4, icon)
 * - Robot/AI icon (bot icon) with blue-cyan gradient
 * - Orange border + pulse animation when suspended (waiting_event)
 * - Gray border + "已超时" label when timeout
 * - Red border + error icon when failed
 * - Real-time step display when running
 * - Status indicators for all execution states
 */
// Helper to extract current step from node data
function getCurrentStep(nodeData: Record<string, unknown>): string {
 // Try to get current step from execution state
 const executionState = nodeData.executionState as Record<string, unknown> | undefined
 if (executionState?.currentStep) {
 return executionState.currentStep as string
 }
 // Try to get from status message
 if (nodeData.statusMessage) {
 return nodeData.statusMessage as string
 }
 // Default running message
 return '正在执行...'
}
// Get container class based on status
function getContainerClass(status: string): string {
 const classes: Record<string, string> = {
 waiting_event: 'status-waiting_event',
 timeout: 'status-timeout',
 failed: 'status-failed',
 running: 'status-running',
 }
 return classes[status] || ''
}
</script>
<template>
 <X6BaseNode v-slot="{ label, description, shortId, nodeData }">
 <div
 class="agent-node-container flex items-center gap-3 px-5 py-4":class="[
 getContainerClass(nodeData.status as string),
 { 'animate-pulse-border': nodeData.status === 'waiting_event' }
 ]"
 >
 <!-- Icon with AI gradient background (larger) -->
 <div
 class="shrink-0 rounded-xl":class="{
 'bg-gradient-to-br from-blue-500/20 to-cyan-400/10': nodeData.status !== 'failed',
 'bg-gradient-to-br from-red-500/20 to-red-400/10': nodeData.status === 'failed',
 }"
 >
 <span:class="[
 'text-xl',
 nodeData.status === 'failed' ? 'icon-[lucide--alert-circle] text-red-500': 'icon-[lucide--bot] text-blue-500',
 nodeData.status === 'running' && 'animate-pulse'
 ]"
 />
 </div>
 <!-- Title + description + status -->
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2">
 <span class="font-medium text-sm truncate":title="label">
 {{ label }}
 </span>
 <!-- Status indicator: Running -->
 <span
 v-if="nodeData.status === 'running'"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-500 shrink-0 flex items-center gap-1"
 >
 <span class="relative flex .5 w-1.5">
 <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
 <span class="relative inline-flex rounded-full .5 w-1.5 bg-blue-500" />
 </span>
 执行中
 </span>
 <!-- Status indicator: Suspended -->
 <span
 v-else-if="nodeData.status === 'waiting_event'"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-500 shrink-0 flex items-center gap-1"
 >
 <span class="relative flex .5 w-1.5">
 <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
 <span class="relative inline-flex rounded-full .5 w-1.5 bg-amber-500" />
 </span>
 挂起中
 </span>
 <!-- Status indicator: Timeout -->
 <span
 v-else-if="nodeData.status === 'timeout'"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0"
 >
 已超时
 </span>
 <!-- Status indicator: Failed -->
 <span
 v-else-if="nodeData.status === 'failed'"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-500 shrink-0"
 >
 失败
 </span>
 </div>
 <!-- Running status: Show current step -->
 <div
 v-if="nodeData.status === 'running'"
 class="text-xs text-blue-500 truncate mt-0.5 flex items-center gap-1"
 >
 <span class="icon-[lucide--loader-2] w-3 animate-spin" />
 {{ getCurrentStep(nodeData as Record<string, unknown>) }}
 </div>
 <!-- Normal description -->
 <div
 v-else-if="description"
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
/* Suspended state border - orange glow with pulse animation */:deep(.x6-node.status-waiting_event) {
 border-color: rgb(245 158 11) !important;
 box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.3);
 animation: pulse-border 2s ease-in-out infinite;
}
/* Timeout state - gray and faded */:deep(.x6-node.status-timeout) {
 border-color: rgb(156 163 175) !important;
 opacity: 0.7;
}
/* Failed state - red border */:deep(.x6-node.status-failed) {
 border-color: rgb(239 68 68) !important;
 box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.2);
}
/* Running state - blue border with subtle glow */:deep(.x6-node.status-running) {
 border-color: rgb(59 130 246) !important;
 box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}
/* Pulse border animation for waiting_event */
@keyframes pulse-border {
 0%, 100% {
 box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.3);
 }
 50% {
 box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.1), 0 0 12px rgba(245, 158, 11, 0.3);
 }
}
.animate-pulse-border {
 animation: pulse-border 2s ease-in-out infinite;
}
</style>
