<script setup lang="ts">
import type { WebhookLog, WebhookLogStatus, WorkItemLog } from '~/api/logs'
import { useHead } from '@vueuse/head'
import { listWebhookLogs, listWorkItemLogs } from '~/api/logs'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from '~/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
useHead({
 title: '日志管理 - Friday AI',
})
const { error: showError } = useToast
// 当前选中的 Tab
const activeTab = ref<'webhook' | 'workitem'>('webhook')
// 过滤器
const projectFilter = ref('')
const statusFilter = ref('')
// 加载状态
const loading = ref(true)
const webhookLogs = ref<WebhookLog>
const workItemLogs = ref<WorkItemLog>
const webhookTotal = ref(0)
const workItemTotal = ref(0)
// 加载项目列表
const projectsStore = useProjectsStore
onMounted(async => {
 try {
 await projectsStore.fetchProjects
 await fetchLogs
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取日志列表')
 }
 finally {
 loading.value = false
 }
})
// 获取日志列表
async function fetchLogs {
 loading.value = true
 try {
 const [webhookResult, workItemResult] = await Promise.all([
 listWebhookLogs({
 project_id: projectFilter.value || undefined,
 status: statusFilter.value as WebhookLogStatus || undefined,
 limit: 50,
 }),
 listWorkItemLogs({
 project_id: projectFilter.value || undefined,
 limit: 50,
 }),
 ])
 webhookLogs.value = webhookResult.items
 webhookTotal.value = webhookResult.total
 workItemLogs.value = workItemResult.items
 workItemTotal.value = workItemResult.total
 }
 finally {
 loading.value = false
 }
}
// 监听过滤条件变化
watch([projectFilter, statusFilter], => {
 fetchLogs
})
// 状态选项
const statusOptions: { value: string, label: string } = [
 { value: '', label: '全部状态' },
 { value: 'accepted', label: '已接受' },
 { value: 'ignored', label: '已忽略' },
 { value: 'error', label: '错误' },
 { value: 'duplicate', label: '重复' },
]
// 获取状态颜色
function getStatusVariant(status: WebhookLogStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
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
function getStatusLabel(status: WebhookLogStatus): string {
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
// 获取项目名称
function getProjectName(projectId: string | null) {
 if (!projectId)
 return '-'
 const project = projectsStore.projectById(projectId)
 return project?.name || projectId.slice(0, 8)
}
</script>
<template>
 <div class="space-y-6">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div>
 <h1 class="text-2xl font-bold">
 飞书数据日志
 </h1>
 <p class="text-muted-foreground">
 查看 Webhook 请求和工作项详情的原始数据
 </p>
 </div>
 </div>
 <!-- 过滤器 -->
 <Card>
 <CardHeader class="pb-3">
 <CardTitle class="text-base">
 筛选条件
 </CardTitle>
 </CardHeader>
 <CardContent>
 <div class="flex flex-wrap gap-4">
 <!-- 项目过滤 -->
 <div class="w-48">
 <Select v-model="projectFilter">
 <SelectTrigger>
 <SelectValue placeholder="选择项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="">
 全部项目
 </SelectItem>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 状态过滤（仅 Webhook） -->
 <div v-if="activeTab === 'webhook'" class="w-40">
 <Select v-model="statusFilter">
 <SelectTrigger>
 <SelectValue placeholder="选择状态" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in statusOptions":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 刷新按钮 -->
 <Button variant="outline" size="icon" @click="fetchLogs">
 <span class="icon-[lucide--refresh-cw]" />
 </Button>
 </div>
 </CardContent>
 </Card>
 <!-- 日志 Tabs -->
 <Tabs v-model="activeTab" class="w-full">
 <TabsList class="grid w-full grid-cols-2 max-w-md">
 <TabsTrigger value="webhook">
 Webhook 日志 ({{ webhookTotal }})
 </TabsTrigger>
 <TabsTrigger value="workitem">
 工作项日志 ({{ workItemTotal }})
 </TabsTrigger>
 </TabsList>
 <!-- Webhook 日志 Tab -->
 <TabsContent value="webhook" class="mt-4">
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <EmptyState
 v-else-if="webhookLogs.length === 0"
 icon="lucide--webhook"
 title="暂无 Webhook 日志"
 description="Webhook 日志将在接收到飞书请求后自动记录"
 />
 <Card v-else>
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead>事件类型</TableHead>
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
 v-for="log in webhookLogs":key="log.id"
 class="cursor-pointer hover:bg-muted/50"
 @click="$router.push(`/logs/webhooks/${log.id}`)"
 >
 <TableCell class="font-medium">
 <div class="max-w-[200px] truncate":title="log.event_type">
 {{ log.event_type || '-' }}
 </div>
 </TableCell>
 <TableCell>
 <span class="text-muted-foreground">
 {{ getProjectName(log.project_id) }}
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
 <RouterLink:to="`/logs/webhooks/${log.id}`" @click.stop>
 <Button variant="ghost" size="sm">
 <span class="icon-[lucide--arrow-right]" />
 </Button>
 </RouterLink>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </Card>
 </TabsContent>
 <!-- 工作项日志 Tab -->
 <TabsContent value="workitem" class="mt-4">
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <EmptyState
 v-else-if="workItemLogs.length === 0"
 icon="lucide--file-text"
 title="暂无工作项日志"
 description="工作项日志将在获取飞书工作项详情后自动记录"
 />
 <Card v-else>
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead>工作项 ID</TableHead>
 <TableHead>类型</TableHead>
 <TableHead>项目</TableHead>
 <TableHead>时间</TableHead>
 <TableHead class="text-right">
 操作
 </TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <TableRow
 v-for="log in workItemLogs":key="log.id"
 class="cursor-pointer hover:bg-muted/50"
 @click="$router.push(`/logs/work-items/${log.id}`)"
 >
 <TableCell class="font-medium">
 {{ log.work_item_id }}
 </TableCell>
 <TableCell>
 <Badge variant="outline">
 {{ log.work_item_type }}
 </Badge>
 </TableCell>
 <TableCell>
 <span class="text-muted-foreground">
 {{ getProjectName(log.project_id) }}
 </span>
 </TableCell>
 <TableCell class="text-muted-foreground">
 {{ formatDate(log.created_at) }}
 </TableCell>
 <TableCell class="text-right">
 <RouterLink:to="`/logs/work-items/${log.id}`" @click.stop>
 <Button variant="ghost" size="sm">
 <span class="icon-[lucide--arrow-right]" />
 </Button>
 </RouterLink>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </Card>
 </TabsContent>
 </Tabs>
 </div>
</template>
