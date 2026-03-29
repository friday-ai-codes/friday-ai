<script setup lang="ts">
/**
 * SubStepTimeline — AI 节点内部子步骤垂直时间线
 *
 * 在 ExecutionNode 展开区域内渲染，左侧垂直连线 + 状态圆点，
 * 右侧步骤名称，类似 GitHub Actions 风格。
 */
import type { SubStep } from '~/types/execution'
defineProps<{
 steps: SubStep
}>
const emit = defineEmits<{
 stepClick: [stepId: string]
}>
function stepStatusColor(status: string): string {
 const map: Record<string, string> = {
 pending: 'bg-gray-300',
 running: 'bg-primary animate-pulse',
 completed: 'bg-green-400',
 failed: 'bg-red-400',
 }
 return map[status] ?? 'bg-gray-300'
}
</script>
<template>
 <div class="mt-2 pl-1">
 <TransitionGroup
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="opacity-0 -translate-y-1"
 enter-to-class="opacity-100 translate-y-0"
 >
 <div
 v-for="(step, index) in steps":key="step.id"
 class="relative flex items-start gap-2 cursor-pointer hover:bg-muted/30 rounded px-1 py-0.5 transition-colors"
 @click.stop="emit('stepClick', step.id)"
 >
 <!-- 垂直连线（除最后一个） -->
 <div
 v-if="index < steps.length - 1"
 class="absolute left-[7px] top-4 w-px h-[calc(100%)] bg-border/50"
 />
 <!-- 状态圆点 -->
 <div
 class="relative z-10 mt-1 w-2.5 .5 rounded-full shrink-0 transition-colors duration-300":class="stepStatusColor(step.status)"
 />
 <!-- 步骤名称 + 错误摘要 -->
 <div class="flex-1 min-w-0">
 <span
 class="text-[11px] leading-tight block truncate":class="step.status === 'failed' ? 'text-red-400': 'text-muted-foreground'"
 >
 {{ step.name }}
 </span>
 <!-- 失败步骤显示错误摘要 -->
 <span
 v-if="step.status === 'failed' && step.output_data?.error"
 class="text-[10px] text-red-400/70 truncate block"
 >
 {{ typeof step.output_data.error === 'string' ? step.output_data.error.slice(0, 50): '' }}
 </span>
 </div>
 </div>
 </TransitionGroup>
 </div>
</template>
