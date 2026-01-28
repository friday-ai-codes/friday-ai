<script setup lang="ts">
import type { TaskStatus } from '~/types'
import { STATUS_LABELS } from '~/types'
const props = defineProps<{
 status: TaskStatus
 showIcon?: boolean
}>
// 状态图标映射
const statusIcons: Record<TaskStatus, string> = {
 pending: 'lucide--clock',
 planning: 'lucide--loader-circle',
 plan_review: 'lucide--eye',
 executing: 'lucide--loader-circle',
 code_review: 'lucide--eye',
 merged: 'lucide--check-circle',
 failed: 'lucide--x-circle',
}
// 是否是运行中状态
const isRunning = computed( =>
 props.status === 'planning' || props.status === 'executing',
)
</script>
<template>
 <div
 class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border transition-colors duration-200 bg-opacity-10 dark:bg-opacity-20 backdrop-blur-sm":class="[
 // Base styles
 status === 'pending' && 'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
 status === 'planning' && 'bg-indigo-100 text-indigo-600 border-indigo-200 dark:bg-indigo-900/30 dark:text-indigo-300 dark:border-indigo-800',
 status === 'plan_review' && 'bg-blue-100 text-blue-600 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800',
 status === 'executing' && 'bg-amber-100 text-amber-600 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800',
 status === 'code_review' && 'bg-purple-100 text-purple-600 border-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-800',
 status === 'merged' && 'bg-emerald-100 text-emerald-600 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
 status === 'failed' && 'bg-red-100 text-red-600 border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800',
 ]"
 >
 <!-- Dot indicator for non-icon mode or running states -->
 <span
 v-if="!showIcon || isRunning"
 class="relative flex .5 w-1.5"
 >
 <span
 v-if="isRunning"
 class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75":class="[
 status === 'planning' && 'bg-indigo-400',
 status === 'executing' && 'bg-amber-400',
 ]"
 />
 <span
 class="relative inline-flex rounded-full .5 w-1.5":class="[
 status === 'pending' && 'bg-slate-400',
 status === 'planning' && 'bg-indigo-500',
 status === 'plan_review' && 'bg-blue-500',
 status === 'executing' && 'bg-amber-500',
 status === 'code_review' && 'bg-purple-500',
 status === 'merged' && 'bg-emerald-500',
 status === 'failed' && 'bg-red-500',
 ]"
 />
 </span>
 <!-- Status Icon -->
 <span
 v-if="showIcon && !isRunning":class="`icon-[${statusIcons[status]}]`"
 class="text-[10px]"
 />
 <span>{{ STATUS_LABELS[status] }}</span>
 </div>
</template>
