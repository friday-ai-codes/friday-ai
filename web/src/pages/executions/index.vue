<script setup lang="ts">
import { useIntervalFn } from '@vueuse/core'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ExecutionCard from '~/components/execution/ExecutionCard.vue'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useProjectsStore } from '~/stores/projects'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const route = useRoute
const router = useRouter
const executionsStore = useExecutionsStore
const projectsStore = useProjectsStore
const workflowsStore = useWorkflowsStore
// Filters
const statusFilter = ref<string>(route.query.status as string || 'all')
const projectFilter = ref<string>(route.query.project_id as string || 'all')
const workflowFilter = ref<string>(route.query.workflow_id as string || 'all')
const stats = computed( => {
 const execs = executionsStore.executions
 return {
 total: execs.length,
 running: execs.filter(e => e.status === 'running').length,
 pending: execs.filter(e => e.status === 'pending').length,
 waitingApproval: execs.filter(e => e.status === 'waiting_approval' || e.node_executions?.some(n => n.status === 'waiting_approval')).length,
 completed: execs.filter(e => e.status === 'completed').length,
 failed: execs.filter(e => e.status === 'failed').length,
 }
})
// Auto-refresh with useIntervalFn - auto cleanup on unmount
const { resume: startAutoRefresh } = useIntervalFn(
 => {
 if (stats.value.running > 0 || stats.value.pending > 0) {
 executionsStore.fetchExecutions(
 workflowFilter.value !== 'all' ? workflowFilter.value: undefined,
 projectFilter.value !== 'all' ? projectFilter.value: undefined,
 )
 }
 },
 5000,
 { immediate: false },
)
const filteredExecutions = computed( => {
 let execs = executionsStore.executions
 if (statusFilter.value && statusFilter.value !== 'all') {
 execs = execs.filter(e => e.status === statusFilter.value)
 }
 return execs
})
const statusOptions = [
 { value: 'all', label: '全部状态' },
 { value: 'running', label: '运行中' },
 { value: 'pending', label: '等待中' },
 { value: 'paused', label: '已暂停' },
 { value: 'completed', label: '已完成' },
 { value: 'failed', label: '失败' },
 { value: 'cancelled', label: '已取消' },
]
async function loadData {
 await Promise.all([
 executionsStore.fetchExecutions(
 workflowFilter.value !== 'all' ? workflowFilter.value: undefined,
 projectFilter.value !== 'all' ? projectFilter.value: undefined,
 ),
 projectsStore.fetchProjects,
 workflowsStore.fetchWorkflows,
 ])
}
// Watch filters and update URL
watch([statusFilter, projectFilter, workflowFilter], => {
 const query: Record<string, string> = {}
 if (statusFilter.value && statusFilter.value !== 'all')
 query.status = statusFilter.value
 if (projectFilter.value && projectFilter.value !== 'all')
 query.project_id = projectFilter.value
 if (workflowFilter.value && workflowFilter.value !== 'all')
 query.workflow_id = workflowFilter.value
 router.replace({ query })
 loadData
})
onMounted( => {
 loadData
 startAutoRefresh
})
</script>
<template>
 <div class="relative space-y-6 max-w-[1400px] mx-auto pb-10">
 <!-- Background decorations -->
 <div class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <!-- Header -->
 <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
 <div class="space-y-1">
 <h1 class="text-3xl font-bold tracking-tight">
 执行监控
 </h1>
 <p class="text-muted-foreground text-sm">
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
 <Button
 v-if="statusFilter !== 'all' || projectFilter !== 'all' || workflowFilter !== 'all'"
 variant="ghost"
 size="sm"
 @click="statusFilter = 'all'; projectFilter = 'all'; workflowFilter = 'all'"
 >
 <span class="icon-[lucide--x] mr-1" />
 清除筛选
 </Button>
 </div>
 <!-- Loading state -->
 <div v-if="executionsStore.loading" class="flex justify-center py-12">
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
 </div>
</template>
