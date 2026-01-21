<script setup lang="ts">
import type { TriggerLog, TriggerLogStatus } from '~/api/logs'
import { markRaw } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card } from '~/components/ui/card'
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
 <Card v-else>
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead>事件类型</TableHead>
 <TableHead>工作项</TableHead>
 <TableHead>项目</TableHead>
 <TableHead>状态</TableHead>
 <TableHead>时间</TableHead>
 <TableHead class="text-right">
 操作
 </TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <TableRow
 v-for="log in logs":key="log.id"
 class="cursor-pointer hover:bg-muted/50"
 @click="openDetail(log.id)"
 >
 <TableCell class="font-medium">
 <div class="max-w-[150px] truncate":title="log.event_type">
 {{ log.event_type || '-' }}
 </div>
 </TableCell>
 <TableCell>
 <div class="max-w-[200px] truncate":title="log.work_item_id || undefined">
 {{ log.work_item_id || '-' }}
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
 <Button variant="ghost" size="sm" @click.stop="openDetail(log.id)">
 <span class="icon-[lucide--eye]" />
 </Button>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </Card>
</template>
