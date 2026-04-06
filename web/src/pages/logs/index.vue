<script setup lang="ts">
import type { ColumnDef } from '@tanstack/vue-table'
import type { TriggerLog, TriggerLogStatus } from '~/api/logs'
import { useHead } from '@vueuse/head'
import { h, markRaw } from 'vue'
import { deleteTriggerLog, listTriggerLogs, retryTriggerLog } from '~/api/logs'
import { useErrorHandler } from '~/composables/useErrorHandler'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import TriggerLogDetailModal from '~/components/logs/TriggerLogDetailModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
useHead({
 title: '触发日志 - Friday AI',
})
const { handleError } = useErrorHandler
const { success } = useToast
// 过滤器
const projectFilter = ref('__all__')
const statusFilter = ref('__all__')
const timeRangeFilter = ref('7')
// 时间范围选项
const timeRangeOptions = [
 { value: '1', label: '近 1 天' },
 { value: '3', label: '近 3 天' },
 { value: '7', label: '近 7 天' },
 { value: '14', label: '近 14 天' },
 { value: '30', label: '近 30 天' },
 { value: 'all', label: '全部时间' },
]
// 加载状态
const loading = ref(true)
const triggerLogs = ref<TriggerLog>
const total = ref(0)
// 加载项目列表
const projectsStore = useProjectsStore
onMounted(async => {
 try {
 await projectsStore.fetchProjects
 await fetchLogs
 }
 catch (e: unknown) {
 handleError(e, '加载日志列表')
 }
 finally {
 loading.value = false
 }
})
// 获取日志列表
async function fetchLogs {
 loading.value = true
 try {
 const projectId = projectFilter.value === '__all__' ? undefined: projectFilter.value
 const status = statusFilter.value === '__all__' ? undefined: statusFilter.value as TriggerLogStatus
 // 计算时间范围
 let createdAfter: string | undefined
 if (timeRangeFilter.value !== 'all') {
 const days = Number.parseInt(timeRangeFilter.value)
 const date = new Date
 date.setDate(date.getDate - days)
 createdAfter = date.toISOString
 }
 const result = await listTriggerLogs({
 project_id: projectId,
 status,
 start_date: createdAfter,
 limit: 50,
 })
 triggerLogs.value = result.items ||
 total.value = result.total || 0
 }
 finally {
 loading.value = false
 }
}
// 监听过滤条件变化
watch([projectFilter, statusFilter, timeRangeFilter], => {
 fetchLogs
})
// 状态选项
const statusOptions: { value: string, label: string, color: string } = [
 { value: '__all__', label: '全部状态', color: 'bg-muted' },
 { value: 'accepted', label: '已接受', color: 'bg-emerald-500' },
 { value: 'ignored', label: '已忽略', color: 'bg-muted-foreground' },
 { value: 'error', label: '错误', color: 'bg-red-500' },
 { value: 'duplicate', label: '重复', color: 'bg-amber-500' },
]
// 获取项目名称
function getProjectName(projectId: string | null) {
 if (!projectId)
 return '-'
 const project = projectsStore.projectById(projectId)
 return project?.name || projectId.slice(0, 8)
}
// 删除确认状态
const deleteDialogOpen = ref(false)
const logToDelete = ref<string | null>(null)
const deleting = ref(false)
function confirmDelete(logId: string) {
 logToDelete.value = logId
 deleteDialogOpen.value = true
}
// 重试日志
async function handleRetry(logId: string) {
 try {
 await retryTriggerLog(logId)
 success('重试成功', '已重新处理该触发事件')
 await fetchLogs
 }
 catch (e: unknown) {
 handleError(e, '重试日志')
 }
}
// 删除日志
async function handleDelete {
 if (!logToDelete.value)
 return
 deleting.value = true
 try {
 await deleteTriggerLog(logToDelete.value)
 success('删除成功', '日志已删除')
 deleteDialogOpen.value = false
 await fetchLogs
 }
 catch (e: unknown) {
 handleError(e, '删除日志')
 }
 finally {
 deleting.value = false
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
 onRefresh: => fetchLogs,
 },
 })
 await open
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
// --- DataTable 列定义 ---
const columns: ColumnDef<TriggerLog> = [
 {
 accessorKey: 'status',
 header: '状态',
 cell: ({ row }) => h(StatusBadge, { type: 'triggerLog', status: row.original.status }),
 enableSorting: false,
 enableGlobalFilter: false,
 },
 {
 accessorKey: 'event_type',
 header: '触发类型',
 cell: ({ row }) => h(Badge, { variant: 'secondary', class: 'text-xs' }, => row.original.event_type),
 enableSorting: true,
 },
 {
 id: 'project',
 header: '项目',
 cell: ({ row }) => h('span', { class: 'text-sm' }, getProjectName(row.original.project_id)),
 enableSorting: false,
 },
 {
 accessorKey: 'work_item_name',
 header: '工作项',
 cell: ({ row }) => h('span', {
 class: 'font-medium truncate block max-w-[200px]',
 title: row.original.work_item_name || undefined,
 }, row.original.work_item_name || '未命名工作项'),
 enableSorting: true,
 },
 {
 accessorKey: 'created_at',
 header: '创建时间',
 cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, formatDate(row.original.created_at)),
 enableSorting: true,
 },
 {
 id: 'actions',
 header: '操作',
 cell: ({ row }) => {
 const log = row.original
 const children =
 // 查看执行按钮（仅当有关联执行时显示）
 if (log.first_execution_id) {
 children.push(
 h('a', {
 href: `/executions/${log.first_execution_id}`,
 class: 'inline-flex items-center justify-center w-8 rounded-md hover:bg-muted/50 transition-colors',
 title: '查看执行',
 onClick: (e: Event) => {
 e.stopPropagation
 e.preventDefault
 useRouter.push(`/executions/${log.first_execution_id}`)
 },
 }, h('span', { class: 'icon-[lucide--play-circle] text-sm text-primary' })),
 )
 }
 // 重试按钮
 children.push(
 h(Button, {
 variant: 'ghost',
 size: 'icon',
 class: ' w-8',
 title: '重试',
 onClick: (e: Event) => {
 e.stopPropagation
 handleRetry(log.id)
 },
 }, => h('span', { class: 'icon-[lucide--refresh-cw] text-sm text-muted-foreground' })),
 )
 // 删除按钮
 children.push(
 h(Button, {
 variant: 'ghost',
 size: 'icon',
 class: ' w-8 hover:bg-destructive/10 hover:text-destructive',
 title: '删除',
 onClick: (e: Event) => {
 e.stopPropagation
 confirmDelete(log.id)
 },
 }, => h('span', { class: 'icon-[lucide--trash-2] text-sm' })),
 )
 return h('div', { class: 'flex items-center gap-1' }, children)
 },
 enableSorting: false,
 enableHiding: false,
 },
]
</script>
<template>
 <PageContainer show-background>
 <!-- 页头 -->
 <PageHeader
 icon="lucide--file-text"
 icon-gradient="from-primary/20 to-primary/10"
 icon-color="text-cyan-500"
 title="触发日志"
 description="查看飞书 Webhook 触发的工作项日志"
 />
 <!-- DataTable -- 集成搜索/排序/分页/列可见性 -->
 <DataTable:data="triggerLogs":columns="columns"
 table-id="logs-list":loading="loading":on-row-click="(log) => openDetail(log.id)"
 >
 <template #filters>
 <!-- 状态过滤 -->
 <Select v-model="statusFilter">
 <SelectTrigger class="w-[140px]">
 <SelectValue placeholder="全部状态" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in statusOptions":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 项目过滤 -->
 <Select v-model="projectFilter">
 <SelectTrigger class="w-[160px]">
 <SelectValue placeholder="全部项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__all__">
 全部项目
 </SelectItem>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 时间范围过滤 -->
 <Select v-model="timeRangeFilter">
 <SelectTrigger class="w-[140px]">
 <SelectValue placeholder="时间范围" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in timeRangeOptions":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Button
 v-if="statusFilter !== '__all__' || projectFilter !== '__all__' || timeRangeFilter !== '7'"
 variant="ghost"
 size="sm"
 @click="statusFilter = '__all__'; projectFilter = '__all__'; timeRangeFilter = '7'"
 >
 <span class="icon-[lucide--x] mr-1" />
 清除筛选
 </Button>
 <div class="flex-1" />
 <!-- 刷新按钮 -->
 <Button variant="ghost" size="icon" class=" w-8" @click="fetchLogs">
 <span class="icon-[lucide--refresh-cw]" />
 </Button>
 </template>
 </DataTable>
 <!-- 删除确认 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除日志"
 description="确定要删除这条触发日志吗？此操作无法撤销。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </PageContainer>
</template>
