<script setup lang="ts">
import type { WorkflowExecution } from '~/stores/useExecutionsStore'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '~/api/client'
import ExecutionCard from '~/components/execution/ExecutionCard.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
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
</script>
<template>
 <PageContainer show-background>
 <!-- Header -->
 <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/10 flex items-center justify-center">
 <span class="icon-[lucide--play-circle] text-2xl text-emerald-500" />
 </div>
 <h1 class="text-2xl font-bold">
 执行监控
 </h1>
 <!-- 后台刷新指示器 -->
 <span
 v-if="isFetching && !isLoading"
 class="icon-[lucide--refresh-cw] text-muted-foreground animate-spin"
 title="正在刷新..."
 />
 </div>
 <p class="text-muted-foreground ml-12">
 实时追踪工作流执行状态
 </p>
 </div>
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
 </div>
 <!-- Filters -->
 <div class="flex flex-wrap items-center gap-3 rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--filter] text-muted-foreground" />
 <span class="text-sm text-muted-foreground">筛选</span>
 </div>
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
 </div>
 <!-- Loading state (only on initial load) -->
 <div v-if="isLoading" class="flex justify-center py-12">
 <div class="animate-spin rounded-full w-8 border-b-2 border-primary" />
 </div>
 <!-- Empty state -->
 <div v-else-if="filteredExecutions.length === 0" class="text-center py-16">
 <div class="inline-flex rounded-2xl bg-gradient-to-br from-muted/50 to-muted/30 mb-4">
 <span class="icon-[lucide--play-circle] text-4xl text-muted-foreground" />
 </div>
 <h3 class="text-lg font-medium mb-2">
 暂无执行记录
 </h3>
 <p class="text-muted-foreground mb-4">
 {{ statusFilter !== 'all' || projectFilter !== 'all' || workflowFilter !== 'all' ? '没有符合筛选条件的执行记录': '运行工作流后，执行记录将显示在这里' }}
 </p>
 <RouterLink to="/workflows">
 <Button>
 <span class="icon-[lucide--workflow] mr-2" />
 查看工作流
 </Button>
 </RouterLink>
 </div>
 <!-- Execution list -->
 <div v-else class="space-y-3">
 <ExecutionCard
 v-for="execution in filteredExecutions":key="execution.id":execution="execution"
 />
 </div>
 </PageContainer>
</template>
