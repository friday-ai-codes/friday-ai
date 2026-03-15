<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import { Skeleton } from '~/components/ui/skeleton'
import { Switch } from '~/components/ui/switch'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
defineProps<{
 workflows: Workflow
 loading?: boolean
}>
const emit = defineEmits<{
 (e: 'click', workflow: Workflow): void
 (e: 'execute', workflow: Workflow): void
 (e: 'delete', workflow: Workflow): void
 (e: 'toggleActive', workflow: Workflow, isActive: boolean): void
}>
function onCardClick(workflow: Workflow) {
 emit('click', workflow)
}
function onExecuteClick(e: Event, workflow: Workflow) {
 e.stopPropagation
 if (!workflow.is_active)
 return
 emit('execute', workflow)
}
function onDeleteClick(e: Event, workflow: Workflow) {
 e.stopPropagation
 emit('delete', workflow)
}
function onToggleActive(checked: boolean, workflow: Workflow) {
 emit('toggleActive', workflow, checked)
}
</script>
<template>
 <TooltipProvider>
 <!-- Loading State -->
 <div v-if="loading" class="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
 <div v-for="i in 8":key="i" class=" rounded-2xl bg-card/80 border border-border/50">
 <div class="flex items-center gap-3 mb-3">
 <Skeleton class=" w-9 rounded-lg" />
 <div class="flex-1">
 <Skeleton class=" w-3/4 mb-1.5" />
 <Skeleton class=" w-1/2" />
 </div>
 </div>
 <div class="flex items-center justify-between">
 <Skeleton class=" w-16" />
 <Skeleton class=" w-20" />
 </div>
 </div>
 </div>
 <!-- Workflow Cards -->
 <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
 <div
 v-for="workflow in workflows":key="workflow.id"
 class="group relative cursor-pointer"
 @click="onCardClick(workflow)"
 >
 <!-- Hover glow effect (only for active workflows) -->
 <div
 v-if="workflow.is_active"
 class="absolute -inset-0.5 bg-gradient-to-r from-teal-500 to-cyan-500 rounded-2xl opacity-0 group-hover:opacity-15 blur-lg transition-opacity duration-500"
 />
 <!-- Card body -->
 <div
 class="relative rounded-2xl backdrop-blur-sm border transition-all duration-300":class="[
 workflow.is_active
 ? 'bg-card/80 border-border/50 group-hover:border-teal-300/50 group-hover:shadow-lg group-hover:shadow-teal-500/10 group-hover:-translate-y-0.5': 'bg-muted/30 border-border/30',
 ]"
 >
 <!-- Header: Icon + Name + Toggle -->
 <div class="flex items-start gap-3 mb-3">
 <!-- Icon -->
 <div
 class=" rounded-lg flex-shrink-0":class="[
 workflow.is_active
 ? 'bg-gradient-to-br from-teal-500/10 to-cyan-500/10': 'bg-muted/50',
 ]"
 >
 <span
 class="text-lg":class="[
 workflow.is_active ? 'icon-[lucide--workflow] text-teal-500': 'icon-[lucide--workflow] text-muted-foreground',
 ]"
 />
 </div>
 <!-- Name & Description -->
 <div class="flex-1 min-w-0">
 <h3
 class="font-medium leading-tight truncate transition-colors":class="[
 workflow.is_active ? 'group-hover:text-primary': 'text-muted-foreground',
 ]"
 >
 {{ workflow.name }}
 </h3>
 <p class="text-xs text-muted-foreground truncate mt-0.5">
 {{ workflow.description || '暂无描述' }}
 </p>
 </div>
 <!-- Toggle Switch -->
 <div @click.stop>
 <Tooltip>
 <TooltipTrigger as-child>
 <Switch:checked="workflow.is_active"
 class="scale-75 origin-right"
 @update:checked="onToggleActive($event, workflow)"
 />
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ workflow.is_active ? '点击禁用': '点击启用' }}</p>
 </TooltipContent>
 </Tooltip>
 </div>
 </div>
 <!-- Actions Row -->
 <div class="flex items-center gap-2 pt-3 border-t border-border/50">
 <!-- Execute Button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="btn btn-primary btn-sm flex-1 text-xs":disabled="!workflow.is_active"
 @click="onExecuteClick($event, workflow)"
 >
 <span class="icon-[lucide--play] mr-1" />
 执行
 </button>
 </TooltipTrigger>
 <TooltipContent v-if="!workflow.is_active" side="top">
 <p>工作流已禁用</p>
 </TooltipContent>
 </Tooltip>
 <!-- Delete Button -->
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="btn btn-ghost btn-icon btn-sm w-7 hover:!bg-red-50 hover:!text-red-500"
 @click="onDeleteClick($event, workflow)"
 >
 <span class="icon-[lucide--trash-2] text-sm" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>删除</p>
 </TooltipContent>
 </Tooltip>
 </div>
 </div>
 </div>
 </div>
 </TooltipProvider>
</template>
