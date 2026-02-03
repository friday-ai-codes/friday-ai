<script setup lang="ts">
import type { NodeExecution, WorkflowExecution } from '~/stores/useExecutionsStore'
import { useIntervalFn } from '@vueuse/core'
import {
 AlertCircle,
 CheckCircle2,
 Clock,
 Loader2,
 Play,
 SkipForward,
 XCircle,
} from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { skipNodeWait, triggerNodeResume } from '~/api/workflow'
import { Button } from '~/components/ui/button'
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
 waiting_event: {
 icon: Clock,
 color: 'text-amber-500',
 bg: 'bg-amber-50 dark:bg-amber-900/20',
 border: 'border-amber-200 dark:border-amber-800',
 label: '等待事件',
 animate: false,
 },
 suspended: {
 icon: Clock,
 color: 'text-amber-500',
 bg: 'bg-amber-50 dark:bg-amber-900/20',
 border: 'border-amber-200 dark:border-amber-800',
 label: '挂起中',
 animate: false,
 },
 partial_success: {
 icon: AlertCircle,
 color: 'text-amber-500',
 bg: 'bg-gradient-to-br from-amber-500/20 to-orange-500/10',
 border: 'border-amber-200 dark:border-amber-800',
 label: '部分完成',
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
// Timer for real-time waiting duration calculation
const now = ref(new Date)
useIntervalFn( => {
 now.value = new Date
}, 1000)
// Calculate waiting duration for waiting_event nodes
function getWaitingDuration(node: NodeExecution): string {
 if (node.status !== 'waiting_event')
 return ''
 const startedAt = node.started_at ? new Date(node.started_at): null
 if (!startedAt)
 return ''
 const duration = Math.floor((now.value.getTime - startedAt.getTime) / 1000)
 if (duration < 60)
 return `${duration} 秒`
 if (duration < 3600)
 return `${Math.floor(duration / 60)} 分钟`
 if (duration < 86400)
 return `${Math.floor(duration / 3600)} 小时`
 return `${Math.floor(duration / 86400)} 天`
}
// Extract waiting condition summary from node approval_data
function getWaitingCondition(node: NodeExecution): string {
 const approvalData = node.approval_data as Record<string, unknown> | undefined
 if (!approvalData?.condition)
 return ''
 const condition = approvalData.condition as {
 conditions?: Array<{ field: string, operator: string, value?: string }>
 logic?: string
 }
 if (!condition.conditions || condition.conditions.length === 0)
 return ''
 const firstCondition = condition.conditions[0]
 const operatorLabels: Record<string, string> = {
 eq: '=',
 ne: '!=',
 gt: '>',
 gte: '>=',
 lt: '<',
 lte: '<=',
 contains: '包含',
 is_empty: '为空',
 is_not_empty: '不为空',
 }
 const op = operatorLabels[firstCondition.operator] || firstCondition.operator
 if (condition.conditions.length === 1) {
 return `${firstCondition.field} ${op} ${firstCondition.value || ''}`
 }
 return `${firstCondition.field} ${op} ${firstCondition.value || ''} 等 ${condition.conditions.length} 个条件`
}
// Extract success/failed counts from node output for partial_success nodes
function getTaskCounts(node: NodeExecution): { success: number, failed: number } | null {
 const output = node.output_data
 if (!output)
 return null
 const successCount = typeof output.success_count === 'number' ? output.success_count: 0
 const failedCount = typeof output.failed_count === 'number' ? output.failed_count: 0
 if (successCount === 0 && failedCount === 0)
 return null
 return { success: successCount, failed: failedCount }
}
// Manual intervention handlers
const isOperating = ref(false)
async function handleSkipWait(node: NodeExecution) {
 if (isOperating.value)
 return
 try {
 isOperating.value = true
 await skipNodeWait(props.execution.id, node.id)
 toast.success('已跳过等待，工作流继续执行')
 }
 catch (error: unknown) {
 const errorMessage = error instanceof Error ? error.message: '操作失败'
 toast.error(errorMessage)
 }
 finally {
 isOperating.value = false
 }
}
async function handleTriggerResume(node: NodeExecution) {
 if (isOperating.value)
 return
 try {
 isOperating.value = true
 await triggerNodeResume(props.execution.id, node.id)
 toast.success('已手动触发唤醒，工作流继续执行')
 }
 catch (error: unknown) {
 const errorMessage = error instanceof Error ? error.message: '操作失败'
 toast.error(errorMessage)
 }
 finally {
 isOperating.value = false
 }
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
 execution.status === 'partial_success' && '[&>div]:bg-amber-500',
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
 <!-- Waiting Event Status with pulse animation -->
 <template v-if="node.status === 'waiting_event'">
 <div class="flex items-center gap-2 text-xs">
 <span class="text-amber-500 font-medium flex items-center gap-1">
 <span class="relative flex w-2">
 <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
 <span class="relative inline-flex rounded-full w-2 bg-amber-500" />
 </span>
 等待中
 </span>
 <span class="text-muted-foreground">
 {{ getWaitingDuration(node) }}
 </span>
 </div>
 <div v-if="getWaitingCondition(node)" class="text-xs text-muted-foreground mt-0.5 truncate">
 等待: {{ getWaitingCondition(node) }}
 </div>
 <!-- Manual intervention buttons -->
 <div class="flex items-center gap-1 mt-2">
 <Button
 variant="outline"
 size="sm"
 class=" text-xs":disabled="isOperating"
 @click.stop="handleSkipWait(node)"
 >
 <SkipForward class="w-3 mr-1" />
 跳过等待
 </Button>
 <Button
 variant="outline"
 size="sm"
 class=" text-xs":disabled="isOperating"
 @click.stop="handleTriggerResume(node)"
 >
 <Play class="w-3 mr-1" />
 手动唤醒
 </Button>
 </div>
 </template>
 <!-- Other statuses -->
 <template v-else>
 <div class="flex items-center gap-2 text-xs text-muted-foreground">
 <span:class="getStatusConfig(node.status).color">
 {{ getStatusConfig(node.status).label }}
 </span>
 <!-- Success/failed counts for partial_success nodes -->
 <template v-if="node.status === 'partial_success' && getTaskCounts(node)">
 <span class="text-emerald-500">{{ getTaskCounts(node)?.success }} 成功</span>
 <span class="text-red-500">{{ getTaskCounts(node)?.failed }} 失败</span>
 </template>
 <span v-if="node.error_message" class="text-red-500 truncate max-w-[120px]">
 - {{ node.error_message }}
 </span>
 </div>
 </template>
 </div>
 </div>
 </div>
 </div>
</template>
<style scoped>
@keyframes pulse-glow {
 0%,
 100% {
 box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4);
 }
 50% {
 box-shadow: 0 0 0 8px rgba(245, 158, 11, 0);
 }
}
.animate-pulse-glow {
 animation: pulse-glow 2s ease-in-out infinite;
}
</style>
