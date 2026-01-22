<script setup lang="ts">
import type { TriggerLog, TriggerLogStatus } from '~/api/logs'
import { markRaw } from 'vue'
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
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card } from '~/components/ui/card'
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuSeparator,
 DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from '~/components/ui/table'
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
// 获取状态颜色
function getStatusVariant(status: TriggerLogStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
 switch (status) {
 case 'accepted':
 return 'default'
 case 'ignored':
 return 'secondary'
 case 'error':
 return 'destructive'
 case 'duplicate':
 return 'outline'
 default:
 return 'outline'
 }
}
// 获取状态标签
function getStatusLabel(status: TriggerLogStatus): string {
 switch (status) {
 case 'accepted':
 return '已接受'
 case 'ignored':
 return '已忽略'
 case 'error':
 return '错误'
 case 'duplicate':
 return '重复'
 default:
 return status
 }
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
 <Card class="rounded-2xl bg-card/70 backdrop-blur-sm border-border/50">
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead>事件类型</TableHead>
 <TableHead>工作项</TableHead>
 <TableHead>项目</TableHead>
 <TableHead>状态</TableHead>
 <TableHead>时间</TableHead>
 <TableHead class="text-right w-[80px]">
 操作
 </TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <TableRow
 v-for="log in logs":key="log.id"
 class="cursor-pointer hover:bg-muted/50 transition-colors"
 @click="openDetail(log.id)"
 >
 <TableCell class="font-medium">
 <div class="max-w-[150px] truncate":title="log.event_type">
 {{ log.event_type || '-' }}
 </div>
 </TableCell>
 <TableCell>
 <div class="max-w-[200px]">
 <div class="truncate font-medium":title="log.work_item_name || undefined">
 {{ log.work_item_name || '-' }}
 </div>
 <div v-if="log.work_item_id" class="text-xs text-muted-foreground truncate">
 #{{ log.work_item_id }}
 </div>
 </div>
 </TableCell>
 <TableCell>
 <span class="text-muted-foreground">
 {{ getProjectName?.(log.project_id) || log.project_id?.slice(0, 8) || '-' }}
 </span>
 </TableCell>
 <TableCell>
 <Badge:variant="getStatusVariant(log.status)">
 {{ getStatusLabel(log.status) }}
 </Badge>
 </TableCell>
 <TableCell class="text-muted-foreground">
 {{ formatDate(log.created_at) }}
 </TableCell>
 <TableCell class="text-right">
 <DropdownMenu>
 <DropdownMenuTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-8" @click.stop>
 <span class="icon-[lucide--more-horizontal] text-muted-foreground" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end">
 <DropdownMenuItem @click.stop="openDetail(log.id)">
 <span class="icon-[lucide--eye] mr-2" />
 查看详情
 </DropdownMenuItem>
 <DropdownMenuItem @click.stop="handleRetry(log.id)">
 <span class="icon-[lucide--refresh-cw] mr-2" />
 重试
 </DropdownMenuItem>
 <DropdownMenuSeparator />
 <DropdownMenuItem
 class="text-destructive focus:text-destructive focus:bg-destructive/10"
 @click.stop="confirmDelete(log.id)"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </Card>
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
