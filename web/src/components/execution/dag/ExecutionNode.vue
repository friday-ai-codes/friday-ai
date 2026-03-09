<script setup lang="ts">
/**
 * ExecutionNode — 只读执行节点组件
 *
 * 基于 BaseWorkflowNode 的视觉风格，但独立实现（不包含编辑器逻辑）。
 * 显示图标 + 名称 + 状态色边框 + 耗时标签 + 瓶颈标记 + AI 成本徽章。
 */
import { Handle, Position } from '@vue-flow/core'
import { computed, ref } from 'vue'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import { useNodeStyle } from '~/components/workflow/editor/nodes/composables/useNodeStyle'
import type { ExecutionNodeData } from './composables/useExecutionDag'
import type { SubStep } from '~/types/execution'
import Badge from '~/components/ui/badge/Badge.vue'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import SubStepTimeline from './SubStepTimeline.vue'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
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
/** 成本格式化 */
const costFormatter = new Intl.NumberFormat('en-US', {
 style: 'currency',
 currency: 'USD',
 minimumFractionDigits: 2,
 maximumFractionDigits: 4,
})
const costText = computed( => {
 if (!props.data.cost) return ''
 const val = Number.parseFloat(props.data.cost.totalCostUsd)
 if (Number.isNaN(val) || val === 0) return '$0.00'
 return costFormatter.format(val)
})
function formatTokenCount(count: number): string {
 if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
 if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`
 return String(count)
}
// 子步骤展开/折叠
const store = useExecutionsStore
const expanded = ref(false)
const nodeSubSteps = computed<SubStep>( => {
 const neId = props.data.nodeExecution?.id
 if (!neId) return
 return store.subSteps[neId] ??
})
const hasSubSteps = computed( =>
 props.data.isAINode && props.data.subStepProgress != null && props.data.subStepProgress.total > 0,
)
const progressText = computed( => {
 const p = props.data.subStepProgress
 if (!p) return ''
 return `${p.completed}/${p.total} steps`
})
function toggleExpand {
 expanded.value = !expanded.value
 if (expanded.value && nodeSubSteps.value.length === 0 && props.data.nodeExecution?.id) {
 store.fetchSubSteps(props.data.nodeExecution.id)
 }
}
function handleSubStepClick(stepId: string) {
 props.data.onSubStepClick?.(props.data.nodeExecution?.id ?? '', stepId)
}
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
 <!-- 底部：耗时 + 从此继续按钮 + 成本徽章 + 瓶颈标签 -->
 <div class="flex items-center justify-between text-xs text-muted-foreground">
 <span class="tabular-nums">{{ durationText }}</span>
 <div class="flex items-center gap-1">
 <!-- 失败节点：从此继续快捷入口 -->
 <TooltipProvider v-if="data.status === 'failed'">
 <Tooltip>
 <TooltipTrigger as-child>
 <button:disabled="!data.canResume":class="[
 'inline-flex items-center justify-center rounded-md transition-colors',
 'w-5 ',
 data.canResume
 ? 'text-primary hover:bg-primary/10 cursor-pointer': 'text-muted-foreground/40 cursor-not-allowed'
 ]"
 @click.stop="data.canResume && data.onResumeClick?.(props.id)"
 >
 <span class="icon-[lucide--play-circle] w-3.5 .5" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="bottom">
 {{ data.canResume ? '从此继续执行': '工作流已修改，无法从此继续' }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <!-- AI 节点成本徽章 + Tooltip -->
 <TooltipProvider v-if="data.cost">
 <Tooltip>
 <TooltipTrigger as-child>
 <Badge
 variant="secondary"
 class="text-[10px] px-1 tabular-nums cursor-default"
 >
 <span class="icon-[lucide--coins] w-2.5 .5 mr-0.5 text-amber-500" />
 {{ costText }}
 </Badge>
 </TooltipTrigger>
 <TooltipContent side="bottom" class="max-w-xs">
 <div class="text-xs space-y-1">
 <div
 v-for="(modelData, modelName) in data.cost.models":key="modelName"
 class="flex items-center justify-between gap-3"
 >
 <span class="font-medium truncate">{{ modelName }}</span>
 <span class="text-muted-foreground tabular-nums whitespace-nowrap">
 {{ formatTokenCount(modelData.input_tokens) }} in /
 {{ formatTokenCount(modelData.output_tokens) }} out
 </span>
 </div>
 <div class="border-t border-border/50 pt-1 flex items-center justify-between gap-3 font-medium">
 <span>总计</span>
 <span class="tabular-nums">{{ formatTokenCount(data.cost.totalTokens) }} tokens</span>
 </div>
 </div>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
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
 <!-- 子步骤展开区域（仅 AI 节点且有进度） -->
 <div v-if="hasSubSteps" class="mt-1.5 pt-1.5 border-t border-border/30">
 <button
 class="flex items-center gap-1.5 w-full text-[11px] text-muted-foreground hover:text-foreground transition-colors"
 @click.stop="toggleExpand"
 >
 <span
 class="icon-[lucide--chevron-right] w-3 transition-transform duration-200":class="{ 'rotate-90': expanded }"
 />
 <span class="tabular-nums">{{ progressText }}</span>
 </button>
 <!-- 展开的时间线 -->
 <div v-if="expanded" class="overflow-hidden">
 <SubStepTimeline:steps="nodeSubSteps"
 @step-click="handleSubStepClick"
 />
 </div>
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
