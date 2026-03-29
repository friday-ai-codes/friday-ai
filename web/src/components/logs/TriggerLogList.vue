<script setup lang="ts">
import type { TriggerLog } from '~/api/logs'
import { markRaw } from 'vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import TriggerLogDetailModal from './TriggerLogDetailModal.vue'
defineProps<{
 logs: TriggerLog
 loading?: boolean
 getProjectName?: (projectId: string | null) => string
}>
const emit = defineEmits<{
 retry: [logId: string]
 delete: [logId: string]
 refresh:
}>
// 删除确认状态
const deleteDialogOpen = ref(false)
const logToDelete = ref<string | null>(null)
function confirmDelete(logId: string) {
 logToDelete.value = logId
 deleteDialogOpen.value = true
}
function handleDelete {
 if (logToDelete.value) {
 emit('delete', logToDelete.value)
 }
 deleteDialogOpen.value = false
 logToDelete.value = null
}
function handleRetry(logId: string) {
 emit('retry', logId)
}
// 格式化日期
function formatDate(dateStr: string) {
 const date = new Date(dateStr)
 return date.toLocaleDateString('zh-CN', {
 month: 'short',
 day: 'numeric',
 hour: '2-digit',
 minute: '2-digit',
 })
}
// 获取执行状态信息
function getExecutionInfo(status: string | null): { icon: string, color: string, label: string } | null {
 if (!status)
 return null
 switch (status) {
 case 'completed':
 return { icon: 'icon-[lucide--circle-check]', color: 'text-emerald-500', label: '执行成功' }
 case 'running':
 return { icon: 'icon-[lucide--loader-2] animate-spin', color: 'text-primary', label: '执行中' }
 case 'pending':
 return { icon: 'icon-[lucide--clock]', color: 'text-amber-500', label: '待执行' }
 case 'failed':
 return { icon: 'icon-[lucide--circle-x]', color: 'text-red-500', label: '执行失败' }
 case 'cancelled':
 return { icon: 'icon-[lucide--circle-slash]', color: 'text-gray-400', label: '已取消' }
 default:
 return { icon: 'icon-[lucide--circle-dot]', color: 'text-gray-400', label: status }
 }
}
// 打开详情弹窗
async function openDetail(logId: string) {
 const { open } = useModal({
 component: markRaw(TriggerLogDetailModal),
 attrs: {
 logId,
 onRetry: => handleRetry(logId),
 onDelete: => confirmDelete(logId),
 onRefresh: => emit('refresh'),
 },
 })
 await open
}
</script>
<template>
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <EmptyState
 v-else-if="!logs || logs.length === 0"
 icon="lucide--webhook"
 title="暂无触发日志"
 description="触发日志将在接收到飞书 Webhook 请求后自动记录"
 />
 <template v-else>
 <!-- 列表头部 -->
 <div class="hidden lg:grid grid-cols-12 gap-4 px-4 py-2 text-xs font-medium text-muted-foreground border-b border-border/50">
 <div class="col-span-5">
 工作项
 </div>
 <div class="col-span-2">
 项目
 </div>
 <div class="col-span-2">
 状态
 </div>
 <div class="col-span-2">
 时间
 </div>
 <div class="col-span-1" />
 </div>
 <!-- 列表内容 -->
 <div class="divide-y divide-border/30">
 <div
 v-for="log in logs":key="log.id"
 class="group grid grid-cols-1 lg:grid-cols-12 gap-2 lg:gap-4 px-4 py-3 hover:bg-muted/30 transition-colors cursor-pointer"
 @click="openDetail(log.id)"
 >
 <!-- 工作项信息 -->
 <div class="lg:col-span-5 flex items-center gap-3 min-w-0">
 <div class="shrink-0 w-8 rounded-lg bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center">
 <span class="icon-[lucide--webhook] text-primary" />
 </div>
 <div class="min-w-0 flex-1">
 <p class="font-medium truncate text-sm":title="log.work_item_name || undefined">
 {{ log.work_item_name || '未命名工作项' }}
 </p>
 <p class="text-xs text-muted-foreground truncate">
 {{ log.event_type }} · #{{ log.work_item_id || '-' }}
 </p>
 </div>
 </div>
 <!-- 项目 -->
 <div class="lg:col-span-2 flex items-center">
 <span class="text-sm text-muted-foreground truncate">
 {{ getProjectName?.(log.project_id) || '-' }}
 </span>
 </div>
 <!-- 状态 -->
 <div class="lg:col-span-2 flex items-center gap-2">
 <StatusBadge type="triggerLog":status="log.status" size="sm" />
 <span
 v-if="getExecutionInfo(log.execution_status)"
 class="inline-flex":title="getExecutionInfo(log.execution_status)?.label"
 >
 <span:class="[getExecutionInfo(log.execution_status)?.icon, getExecutionInfo(log.execution_status)?.color]" />
 </span>
 </div>
 <!-- 时间 -->
 <div class="lg:col-span-2 flex items-center">
 <span class="text-sm text-muted-foreground">
 {{ formatDate(log.created_at) }}
 </span>
 </div>
 <!-- 操作 -->
 <div class="lg:col-span-1 flex items-center justify-end gap-1">
 <RouterLink
 v-if="log.first_execution_id":to="`/executions/${log.first_execution_id}`"
 class="inline-flex items-center justify-center w-7 rounded-md opacity-0 group-hover:opacity-100 transition-opacity hover:bg-muted/50"
 title="查看执行"
 @click.stop
 >
 <span class="icon-[lucide--play-circle] text-sm text-primary" />
 </RouterLink>
 <Button
 variant="ghost"
 size="icon"
 class=" w-7 opacity-0 group-hover:opacity-100 transition-opacity"
 title="重试"
 @click.stop="handleRetry(log.id)"
 >
 <span class="icon-[lucide--refresh-cw] text-sm text-muted-foreground" />
 </Button>
 <Button
 variant="ghost"
 size="icon"
 class=" w-7 opacity-0 group-hover:opacity-100 transition-opacity"
 title="删除"
 @click.stop="confirmDelete(log.id)"
 >
 <span class="icon-[lucide--trash-2] text-sm text-muted-foreground hover:text-destructive" />
 </Button>
 <span class="icon-[lucide--chevron-right] text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
 </div>
 </div>
 </div>
 <!-- 删除确认弹窗 -->
 <AlertDialog v-model:open="deleteDialogOpen">
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>确认删除</AlertDialogTitle>
 <AlertDialogDescription>
 确定要删除这条触发日志吗？此操作无法撤销。
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel>取消</AlertDialogCancel>
 <AlertDialogAction
 class="bg-destructive text-destructive-foreground hover:bg-destructive/90"
 @click="handleDelete"
 >
 删除
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </template>
</template>
