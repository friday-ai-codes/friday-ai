<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow
} from '~/components/ui/table'
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuTrigger
} from '~/components/ui/dropdown-menu'
import { Button } from '~/components/ui/button'
import { Badge } from '~/components/ui/badge'
import { Skeleton } from '~/components/ui/skeleton'
import {
 Play,
 MoreHorizontal,
 CheckCircle2,
 XCircle,
 Loader2,
 Circle,
 Edit,
 Trash2
} from 'lucide-vue-next'
const props = defineProps<{
 workflows: Workflow
 loading?: boolean
}>
const emit = defineEmits<{
 (e: 'click', workflow: Workflow): void
 (e: 'execute', workflow: Workflow): void
 (e: 'edit', workflow: Workflow): void
 (e: 'delete', workflow: Workflow): void
}>
function getStatusIcon(status?: string) {
 switch (status?.toLowerCase) {
 case 'success':
 case 'succeeded':
 case 'completed':
 return { icon: CheckCircle2, class: 'text-green-500' }
 case 'failed':
 case 'failure':
 case 'error':
 return { icon: XCircle, class: 'text-red-500' }
 case 'running':
 case 'pending':
 case 'processing':
 return { icon: Loader2, class: 'text-blue-500 animate-spin' }
 default:
 return { icon: Circle, class: 'text-muted-foreground' }
 }
}
function getRelativeTime(dateStr?: string) {
 if (!dateStr) return '-'
 const date = new Date(dateStr)
 const now = new Date
 const diffMs = now.getTime - date.getTime
 const diffMins = Math.floor(diffMs / 60000)
 const diffHours = Math.floor(diffMs / 3600000)
 const diffDays = Math.floor(diffMs / 86400000)
 if (diffMins < 1)
 return '刚刚'
 if (diffMins < 60)
 return `${diffMins} 分钟前`
 if (diffHours < 24)
 return `${diffHours} 小时前`
 if (diffDays < 7)
 return `${diffDays} 天前`
 return date.toLocaleDateString('zh-CN')
}
function onRowClick(workflow: Workflow) {
 emit('click', workflow)
}
function onRunClick(e: Event, workflow: Workflow) {
 e.stopPropagation
 emit('execute', workflow)
}
function onEditClick(workflow: Workflow) {
 emit('edit', workflow)
}
function onDeleteClick(workflow: Workflow) {
 emit('delete', workflow)
}
</script>
<template>
 <div class="rounded-md border">
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead class="w-[50px]"></TableHead>
 <TableHead>工作流</TableHead>
 <TableHead>触发器</TableHead>
 <TableHead>最近运行</TableHead>
 <TableHead class="w-[100px] text-right">操作</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <template v-if="loading">
 <TableRow v-for="i in 5":key="i">
 <TableCell><Skeleton class=" w-8 rounded-full" /></TableCell>
 <TableCell>
 <div class="space-y-2">
 <Skeleton class=" w-[200px]" />
 <Skeleton class=" w-[150px]" />
 </div>
 </TableCell>
 <TableCell><Skeleton class=" w-20" /></TableCell>
 <TableCell>
 <div class="space-y-2">
 <Skeleton class=" w-[100px]" />
 <Skeleton class=" w-[80px]" />
 </div>
 </TableCell>
 <TableCell class="text-right"><Skeleton class=" w-8 ml-auto" /></TableCell>
 </TableRow>
 </template>
 <template v-else-if="!workflows || workflows.length === 0">
 <TableRow>
 <TableCell colspan="5" class=" text-center">
 暂无工作流
 </TableCell>
 </TableRow>
 </template>
 <template v-else>
 <TableRow
 v-for="workflow in workflows":key="workflow.id"
 class="cursor-pointer hover:bg-muted/50 transition-colors"
 @click="onRowClick(workflow)"
 >
 <!-- Status -->
 <TableCell>
 <component:is="getStatusIcon(workflow.last_execution?.status).icon"
 class=" w-5":class="getStatusIcon(workflow.last_execution?.status).class"
 />
 </TableCell>
 <!-- Workflow Name & Description -->
 <TableCell>
 <div class="flex flex-col">
 <span class="font-medium">{{ workflow.name }}</span>
 <span class="text-sm text-muted-foreground line-clamp-1":title="workflow.description">
 {{ workflow.description || '暂无描述' }}
 </span>
 </div>
 </TableCell>
 <!-- Trigger -->
 <TableCell>
 <Badge variant="secondary" class="capitalize">
 {{ workflow.trigger_type }}
 </Badge>
 </TableCell>
 <!-- Last Run -->
 <TableCell>
 <div class="flex flex-col text-sm">
 <span v-if="workflow.last_execution" class="font-medium capitalize">
 {{ workflow.last_execution.status }}
 </span>
 <span v-else class="text-muted-foreground">-</span>
 <span v-if="workflow.last_execution" class="text-xs text-muted-foreground">
 {{ getRelativeTime(workflow.last_execution.created_at) }}
 </span>
 </div>
 </TableCell>
 <!-- Actions -->
 <TableCell class="text-right">
 <div class="flex items-center justify-end gap-2" @click.stop>
 <Button
 variant="ghost"
 size="icon"
 class=" w-8 hover:text-primary"
 title="执行工作流"
 @click="onRunClick($event, workflow)"
 >
 <Play class=" w-4" />
 </Button>
 <DropdownMenu>
 <DropdownMenuTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-8">
 <MoreHorizontal class=" w-4" />
 <span class="sr-only">打开菜单</span>
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end">
 <DropdownMenuItem @click="onEditClick(workflow)">
 <Edit class="mr-2 w-4" />
 编辑
 </DropdownMenuItem>
 <DropdownMenuItem @click="onDeleteClick(workflow)" class="text-red-600 focus:text-red-600">
 <Trash2 class="mr-2 w-4" />
 删除
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 </TableCell>
 </TableRow>
 </template>
 </TableBody>
 </Table>
 </div>
</template>
