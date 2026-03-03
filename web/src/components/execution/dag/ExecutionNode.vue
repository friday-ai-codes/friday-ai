<script setup lang="ts">
/**
 * ExecutionNode — 只读执行节点组件
 *
 * 基于 BaseWorkflowNode 的视觉风格，但独立实现（不包含编辑器逻辑）。
 * 显示图标 + 名称 + 状态色边框 + 耗时标签 + 瓶颈标记。
 */
import { Handle, Position } from '@vue-flow/core'
import { computed } from 'vue'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import { useNodeStyle } from '~/components/workflow/editor/nodes/composables/useNodeStyle'
import type { ExecutionNodeData } from './composables/useExecutionDag'
import Badge from '~/components/ui/badge/Badge.vue'
const props = defineProps<{
 id: string
 data: ExecutionNodeData
}>
const visual = computed( => getNodeVisual(props.data.nodeType))
const style = computed( => useNodeStyle(visual.value.color).value)
/** 执行状态 → 边框色映射（覆盖默认的节点类型色） */
const statusBorderClass = computed( => {
 const map: Record<string, string> = {
 running: 'border-blue-400/80 node-running-border',
 completed: 'border-green-400/60',
 failed: 'border-red-400/70',
 pending: 'border-gray-300/50',
 skipped: 'border-gray-300/30 opacity-50',
 waiting_approval: 'border-orange-400/60',
 waiting_event: 'border-indigo-400/60',
 paused: 'border-yellow-400/60',
 cancelled: 'border-gray-400/50',
 }
 return map[props.data.status] ?? 'border-gray-300/50'
})
/** 瓶颈光晕 — 用 shadow + ring 避免与状态色 border 冲突 */
const bottleneckClass = computed( => {
 if (!props.data.isBottleneck) return ''
 return props.data.bottleneckLevel === 'critical'
 ? 'shadow-[0_0_12px_rgba(239,68,68,0.4)] ring-2 ring-red-400/50': 'shadow-[0_0_10px_rgba(234,179,8,0.35)] ring-2 ring-yellow-400/50'
})
const durationText = computed( => {
 const seconds = props.data.elapsed ?? props.data.duration
 if (seconds == null) return '-'
 if (seconds < 60) return `${Math.round(seconds)}s`
 return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
})
/** 状态指示点颜色 */
const statusDotClass = computed( => {
 const map: Record<string, string> = {
 running: 'bg-blue-400 animate-pulse',
 completed: 'bg-green-400',
 failed: 'bg-red-400',
 pending: 'bg-gray-300',
 skipped: 'bg-gray-300',
 waiting_approval: 'bg-orange-400 animate-pulse',
 waiting_event: 'bg-indigo-400 animate-pulse',
 paused: 'bg-yellow-400',
 cancelled: 'bg-gray-400',
 }
 return map[props.data.status] ?? 'bg-gray-300'
})
</script>
<template>
 <div>
 <Handle type="target":position="Position.Top" />
 <div
 class="w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl
 transition-all duration-200 cursor-pointer
 hover:shadow-md hover:border-opacity-70":class="[statusBorderClass, bottleneckClass]"
 >
 <!-- 头部：图标 + 名称 -->
 <div class="flex items-center gap-2 mb-1.5">
 <div:class="['bg-gradient-to-br rounded-lg .5', style.iconBg]">
 <component:is="visual.icon" class="w-4 ":class="style.iconColor" />
 </div>
 <span class="text-sm font-medium text-foreground truncate flex-1">
 {{ data.name }}
 </span>
 <!-- 状态指示点 -->
 <div class="w-2 rounded-full shrink-0":class="statusDotClass" />
 </div>
 <!-- 底部：耗时 + 瓶颈标签 -->
 <div class="flex items-center justify-between text-xs text-muted-foreground">
 <span class="tabular-nums">{{ durationText }}</span>
 <Badge
 v-if="data.isBottleneck"
 variant="outline"
 class="text-[10px] px-1":class="data.bottleneckLevel === 'critical'
 ? 'border-red-400/50 text-red-500': 'border-yellow-400/50 text-yellow-600'"
 >
 {{ data.bottleneckLevel === 'critical' ? '瓶颈 #1': '瓶颈' }}
 </Badge>
 </div>
 </div>
 <Handle type="source":position="Position.Bottom" />
 </div>
</template>
<style scoped>
/* 运行中节点脉冲动画 */
.node-running-border {
 animation: node-pulse 2s ease-in-out infinite;
}
@keyframes node-pulse {
 0%, 100% {
 border-color: rgba(96, 165, 250, 0.5);
 box-shadow: 0 0 0 0 rgba(96, 165, 250, 0.2);
 }
 50% {
 border-color: rgba(96, 165, 250, 0.8);
 box-shadow: 0 0 8px 2px rgba(96, 165, 250, 0.15);
 }
}
</style>
