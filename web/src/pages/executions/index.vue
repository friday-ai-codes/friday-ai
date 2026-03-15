<script setup lang="ts">
import type { WorkflowExecution } from '~/stores/useExecutionsStore'
import type { ColumnDef } from '@tanstack/vue-table'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, h, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '~/api/client'
import DataTable from '~/components/common/DataTable.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useProjectsStore } from '~/stores/projects'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
const workflowsStore = useWorkflowsStore
// Filters
const statusFilter = ref<string>(route.query.status as string || 'all')
const projectFilter = ref<string>(route.query.project_id as string || 'all')
const workflowFilter = ref<string>(route.query.workflow_id as string || 'all')
const timeRangeFilter = ref<string>(route.query.days as string || '7')
// 时间范围选项
const timeRangeOptions = [
 { value: '1', label: '近 1 天' },
 { value: '3', label: '近 3 天' },
 { value: '7', label: '近 7 天' },
 { value: '14', label: '近 14 天' },
 { value: '30', label: '近 30 天' },
 { value: 'all', label: '全部时间' },
]
const statusOptions = [
 { value: 'all', label: '全部状态' },
 { value: 'running', label: '运行中' },
 { value: 'pending', label: '等待中' },
 { value: 'paused', label: '已暂停' },
 { value: 'completed', label: '已完成' },
 { value: 'failed', label: '失败' },
 { value: 'cancelled', label: '已取消' },
]
// 计算查询参数
const queryParams = computed( => {
 const params: Record<string, string> = {}
 if (workflowFilter.value !== 'all')
 params.workflow_id = workflowFilter.value
 if (projectFilter.value !== 'all')
 params.project_id = projectFilter.value
 if (timeRangeFilter.value !== 'all') {
 const days = Number.parseInt(timeRangeFilter.value)
 const date = new Date
 date.setDate(date.getDate - days)
 params.created_after = date.toISOString
 }
 return params
})
// 使用 TanStack Query 获取执行列表
const { data: executions, isLoading, isFetching } = useQuery({
 queryKey: ['executions', queryParams],
 queryFn: async => {
 const response = await api.get<{ results: WorkflowExecution } | WorkflowExecution>(
 '/workflow-executions/',
 queryParams.value,
 )
 return Array.isArray(response) ? response: response.results ||
 },
 placeholderData: keepPreviousData, // 刷新时保持旧数据，避免抖动
 refetchInterval: (query) => {
 // 只有在有运行中或等待中的任务时才自动刷新
 const data = query.state.data
 if (data?.some(e => e.status === 'running' || e.status === 'pending')) {
 return 5000
 }
 return false
 },
 staleTime: 3000, // 3秒内不重新请求
})
// 加载项目和工作流列表（用于筛选下拉框）
useQuery({
 queryKey: ['projects'],
 queryFn: => projectsStore.fetchProjects,
 staleTime: 60000,
})
useQuery({
 queryKey: ['workflows'],
 queryFn: => workflowsStore.fetchWorkflows,
 staleTime: 60000,
})
// 计算统计数据
const stats = computed( => {
 const execs = executions.value ||
 return {
 total: execs.length,
 running: execs.filter(e => e.status === 'running').length,
 pending: execs.filter(e => e.status === 'pending').length,
 waitingApproval: execs.filter(e => e.status === 'waiting_approval' || e.node_executions?.some(n => n.status === 'waiting_approval')).length,
 completed: execs.filter(e => e.status === 'completed').length,
 failed: execs.filter(e => e.status === 'failed').length,
 }
})
// 根据状态筛选
const filteredExecutions = computed( => {
 let execs = executions.value ||
 if (statusFilter.value && statusFilter.value !== 'all') {
 execs = execs.filter(e => e.status === statusFilter.value)
 }
 return execs
})
// Watch filters and update URL
watch([statusFilter, projectFilter, workflowFilter, timeRangeFilter], => {
 const query: Record<string, string> = {}
 if (statusFilter.value && statusFilter.value !== 'all')
 query.status = statusFilter.value
 if (projectFilter.value && projectFilter.value !== 'all')
 query.project_id = projectFilter.value
 if (workflowFilter.value && workflowFilter.value !== 'all')
 query.workflow_id = workflowFilter.value
 if (timeRangeFilter.value && timeRangeFilter.value !== '7')
 query.days = timeRangeFilter.value
 router.replace({ query })
})
// --- 辅助函数 ---
/** 通过 workflowsStore 反查项目名称 */
function getProjectName(workflowId: string): string {
 const wf = workflowsStore.workflows.find(w => w.id === workflowId)
 return wf?.project_name || '-'
}
/** 触发类型中文标签映射 */
const triggerTypeLabels: Record<string, string> = {
 manual: '手动触发',
 webhook: 'Webhook',
 schedule: '定时触发',
 event: '事件触发',
}
/** 格式化耗时 */
function formatDuration(duration: number | null): string {
 if (duration == null) return '-'
 if (duration < 60) return `${Math.round(duration)}s`
 const mins = Math.floor(duration / 60)
 const secs = Math.round(duration % 60)
 return `${mins}m ${secs}s`
}
// --- DataTable 列定义 ---
const columns: ColumnDef<WorkflowExecution> = [
 {
 accessorKey: 'status',
 header: '状态',
 cell: ({ row }) => h(StatusBadge, { type: 'execution', status: row.original.status }),
 enableSorting: false,
 enableGlobalFilter: false,
 },
 {
 accessorKey: 'workflow_name',
 header: '工作流',
 cell: ({ row }) => h('span', { class: 'font-medium text-foreground' }, row.original.workflow_name),
 enableSorting: true,
 },
 {
 id: 'project',
 header: '项目',
 cell: ({ row }) => h('span', { class: 'text-sm' }, getProjectName(row.original.workflow)),
 enableSorting: false,
 },
 {
 accessorKey: 'trigger_type',
 header: '触发类型',
 cell: ({ row }) => h('span', { class: 'text-sm' }, triggerTypeLabels[row.original.trigger_type] || row.original.trigger_type),
 enableSorting: false,
 },
 {
 accessorKey: 'duration',
 header: '耗时',
 cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, formatDuration(row.original.duration)),
 enableSorting: true,
 },
 {
 accessorKey: 'created_at',
 header: '创建时间',
 cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, new Date(row.original.created_at).toLocaleString('zh-CN')),
 enableSorting: true,
 },
]
</script>
<template>
 <PageContainer show-background>
 <!-- Header -->
 <PageHeader
 icon="lucide--play-circle"
 icon-gradient="from-emerald-500/20 to-teal-500/10"
 icon-color="text-emerald-500"
 title="执行监控"
 description="实时追踪工作流执行状态"
 >
 <template #title-suffix>
 <!-- 后台刷新指示器 -->
 <span
 v-if="isFetching && !isLoading"
 class="icon-[lucide--refresh-cw] text-muted-foreground animate-spin"
 title="正在刷新..."
 />
 </template>
 <template #actions>
 <!-- Stats cards -->
 <div class="flex flex-wrap gap-3">
 <div class="flex items-center gap-3 px-4 py-2 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class=" rounded-xl bg-gradient-to-br from-blue-500/20 to-blue-400/10">
 <span class="icon-[lucide--loader-2] w-5 text-blue-500":class="stats.running > 0 ? 'animate-spin': ''" />
 </div>
 <div>
 <span class="text-xs text-muted-foreground block">运行中</span>
 <span class="text-lg font-bold">{{ stats.running }}</span>
 </div>
 </div>
 <div class="flex items-center gap-3 px-4 py-2 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class=" rounded-xl bg-gradient-to-br from-orange-500/20 to-orange-400/10">
 <span class="icon-[lucide--user-check] w-5 text-orange-500" />
 </div>
 <div>
 <span class="text-xs text-muted-foreground block">待审批</span>
 <span class="text-lg font-bold">{{ stats.waitingApproval }}</span>
 </div>
 </div>
 <div class="flex items-center gap-3 px-4 py-2 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class=" rounded-xl bg-gradient-to-br from-emerald-500/20 to-emerald-400/10">
 <span class="icon-[lucide--check-circle] w-5 text-emerald-500" />
 </div>
 <div>
 <span class="text-xs text-muted-foreground block">已完成</span>
 <span class="text-lg font-bold">{{ stats.completed }}</span>
 </div>
 </div>
 <div class="flex items-center gap-3 px-4 py-2 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class=" rounded-xl bg-gradient-to-br from-red-500/20 to-red-400/10">
 <span class="icon-[lucide--x-circle] w-5 text-red-500" />
 </div>
 <div>
 <span class="text-xs text-muted-foreground block">失败</span>
 <span class="text-lg font-bold">{{ stats.failed }}</span>
 </div>
 </div>
 </div>
 </template>
 </PageHeader>
 <!-- DataTable -- 集成搜索/排序/分页/列可见性 -->
 <DataTable:data="filteredExecutions":columns="columns"
 table-id="executions-list":loading="isLoading":on-row-click="(execution) => router.push(`/executions/${execution.id}`)"
 >
 <template #filters>
 <Select v-model="statusFilter">
 <SelectTrigger class="w-[140px]">
 <SelectValue placeholder="全部状态" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="opt in statusOptions":key="opt.value":value="opt.value">
 {{ opt.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Select v-model="projectFilter">
 <SelectTrigger class="w-[160px]">
 <SelectValue placeholder="全部项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="all">
 全部项目
 </SelectItem>
 <SelectItem v-for="project in projectsStore.projects":key="project.id":value="project.id">
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Select v-model="workflowFilter">
 <SelectTrigger class="w-[180px]">
 <SelectValue placeholder="全部工作流" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="all">
 全部工作流
 </SelectItem>
 <SelectItem v-for="workflow in workflowsStore.workflows":key="workflow.id":value="workflow.id">
 {{ workflow.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Select v-model="timeRangeFilter">
 <SelectTrigger class="w-[140px]">
 <SelectValue placeholder="时间范围" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="opt in timeRangeOptions":key="opt.value":value="opt.value">
 {{ opt.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Button
 v-if="statusFilter !== 'all' || projectFilter !== 'all' || workflowFilter !== 'all' || timeRangeFilter !== '7'"
 variant="ghost"
 size="sm"
 @click="statusFilter = 'all'; projectFilter = 'all'; workflowFilter = 'all'; timeRangeFilter = '7'"
 >
 <span class="icon-[lucide--x] mr-1" />
 清除筛选
 </Button>
 </template>
 </DataTable>
 </PageContainer>
</template>
