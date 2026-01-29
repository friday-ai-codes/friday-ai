<script setup lang="ts">
import type { NodeExecution, WorkflowExecution } from '~/stores/useExecutionsStore'
import {
 AlertCircle,
 CheckCircle2,
 Clock,
 Loader2,
 XCircle,
} from 'lucide-vue-next'
import { computed } from 'vue'
import { Progress } from '~/components/ui/progress'
import { cn } from '~/lib/utils'
interface Props {
 execution: WorkflowExecution
 nodeExecutions: NodeExecution
 compact?: boolean
}
const props = withDefaults(defineProps<Props>, {
 compact: false,
})
const emit = defineEmits<{
 (e: 'selectNode', node: NodeExecution): void
}>
const statusConfig = {
 pending: {
 icon: Clock,
 color: 'text-gray-500',
 bg: 'bg-gray-100 dark:bg-gray-800',
 border: 'border-gray-200 dark:border-gray-700',
 label: '等待中',
 animate: false,
 },
 running: {
 icon: Loader2,
 color: 'text-blue-500',
 bg: 'bg-blue-50 dark:bg-blue-900/20',
 border: 'border-blue-200 dark:border-blue-800',
 label: '运行中',
 animate: true,
 },
 completed: {
 icon: CheckCircle2,
 color: 'text-green-500',
 bg: 'bg-green-50 dark:bg-green-900/20',
 border: 'border-green-200 dark:border-green-800',
 label: '已完成',
 animate: false,
 },
 failed: {
 icon: XCircle,
 color: 'text-red-500',
 bg: 'bg-red-50 dark:bg-red-900/20',
 border: 'border-red-200 dark:border-red-800',
 label: '失败',
 animate: false,
 },
 waiting_approval: {
 icon: Clock,
 color: 'text-amber-500',
 bg: 'bg-amber-50 dark:bg-amber-900/20',
 border: 'border-amber-200 dark:border-amber-800',
 label: '待审批',
 animate: false,
 },
 paused: {
 icon: AlertCircle,
 color: 'text-yellow-500',
 bg: 'bg-yellow-50 dark:bg-yellow-900/20',
 border: 'border-yellow-200 dark:border-yellow-800',
 label: '已暂停',
 animate: false,
 },
 cancelled: {
 icon: XCircle,
 color: 'text-gray-500',
 bg: 'bg-gray-100 dark:bg-gray-800',
 border: 'border-gray-200 dark:border-gray-700',
 label: '已取消',
 animate: false,
 },
} as const
function getStatusConfig(status: string) {
 return statusConfig[status as keyof typeof statusConfig] || statusConfig.pending
}
const formattedDuration = computed( => {
 if (!props.execution.duration)
 return '-'
 const seconds = Math.round(props.execution.duration)
 if (seconds < 60)
 return `${seconds}s`
 const minutes = Math.floor(seconds / 60)
 const remainingSeconds = seconds % 60
 return `${minutes}m ${remainingSeconds}s`
})
function formatNodeDuration(duration: number | null) {
 if (!duration)
 return ''
 if (duration < 1)
 return '<1s'
 return `${Math.round(duration)}s`
}
</script>
<template>
 <div:class="cn('flex flex-col gap-4', compact ? 'text-sm': '')">
 <!-- Overall Status -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <div:class="cn(
 '.5 rounded-md border',
 getStatusConfig(execution.status).bg,
 getStatusConfig(execution.status).border,
 )"
 >
 <component:is="getStatusConfig(execution.status).icon":class="cn(
 'w-4 ',
 getStatusConfig(execution.status).color,
 getStatusConfig(execution.status).animate && 'animate-spin',
 )"
 />
 </div>
 <div class="flex flex-col">
 <span class="font-medium leading-none">
 {{ getStatusConfig(execution.status).label }}
 </span>
 <span v-if="!compact" class="text-xs text-muted-foreground mt-1">
 {{ formattedDuration }}
 </span>
 </div>
 </div>
 <div v-if="compact" class="text-xs text-muted-foreground">
 {{ formattedDuration }}
 </div>
 </div>
 <!-- Progress Bar -->
 <div class="space-y-1.5">
 <div class="flex justify-between text-xs text-muted-foreground">
 <span>进度 ({{ execution.completed_nodes }}/{{ execution.total_nodes }})</span>
 <span>{{ Math.round(execution.progress) }}%</span>
 </div>
 <Progress:model-value="execution.progress"
 class="":class="cn(
 execution.status === 'failed' && '[&>div]:bg-red-500',
 execution.status === 'completed' && '[&>div]:bg-green-500',
 )"
 />
 </div>
 </div>
 <!-- Node List -->
 <div class="flex flex-col gap-2 overflow-y-auto max-h-[calc(100vh-12rem)] pr-1">
 <div
 v-for="node in nodeExecutions":key="node.id"
 class="group flex items-center gap-3 rounded-lg border border-transparent hover:bg-accent hover:border-border transition-all cursor-pointer"
 @click="emit('selectNode', node)"
 >
 <!-- Node Status Icon -->
 <div:class="cn(
 'flex-shrink-0 w-6 rounded-full flex items-center justify-center border',
 getStatusConfig(node.status).bg,
 getStatusConfig(node.status).border,
 )"
 >
 <component:is="getStatusConfig(node.status).icon":class="cn(
 'w-3.5 .5',
 getStatusConfig(node.status).color,
 getStatusConfig(node.status).animate && 'animate-spin',
 )"
 />
 </div>
 <!-- Node Info -->
 <div class="flex-1 min-w-0">
 <div class="flex items-center justify-between mb-0.5">
 <span class="font-medium truncate text-sm">
 {{ node.node_name || node.node }}
 </span>
 <span v-if="node.duration" class="text-xs text-muted-foreground flex-shrink-0 ml-2">
 {{ formatNodeDuration(node.duration) }}
 </span>
 </div>
 <div class="flex items-center gap-2 text-xs text-muted-foreground">
 <span:class="getStatusConfig(node.status).color">
 {{ getStatusConfig(node.status).label }}
 </span>
 <span v-if="node.error_message" class="text-red-500 truncate max-w-[120px]">
 - {{ node.error_message }}
 </span>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
