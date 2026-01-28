<script setup lang="ts">
import type { TaskStatus } from '~/types'
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useTasksCompatStore } from '~/stores/tasksCompat'
import { STATUS_LABELS } from '~/types'
useHead({
 title: '任务列表 - Friday AI',
})
const route = useRoute
const _router = useRouter
const tasksStore = useTasksCompatStore
const projectsStore = useProjectsStore
const { error: showError } = useToast
// 从 URL 获取过滤参数
const projectFilter = ref<string>(route.query.project_id as string || '__all__')
const statusFilter = ref<string>(route.query.status as string || '__all__')
// 加载数据
const loading = ref(true)
onMounted(async => {
 try {
 await projectsStore.fetchProjects
 await fetchTasks
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取任务列表')
 }
 finally {
 loading.value = false
 }
})
// 获取任务列表
async function fetchTasks {
 const projectId = projectFilter.value === '__all__' ? undefined: projectFilter.value
 const status = statusFilter.value === '__all__' ? undefined: statusFilter.value as TaskStatus
 await tasksStore.fetchTasks({
 project_id: projectId,
 status,
 })
}
// 监听过滤条件变化
watch([projectFilter, statusFilter], => {
 fetchTasks
})
// 状态选项
const statusOptions: { value: string, label: string } = [
 { value: '__all__', label: '全部状态' },
 { value: 'pending', label: STATUS_LABELS.pending },
 { value: 'planning', label: STATUS_LABELS.planning },
 { value: 'plan_review', label: STATUS_LABELS.plan_review },
 { value: 'executing', label: STATUS_LABELS.executing },
 { value: 'code_review', label: STATUS_LABELS.code_review },
 { value: 'merged', label: STATUS_LABELS.merged },
 { value: 'failed', label: STATUS_LABELS.failed },
]
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
function getProjectName(projectId: string) {
 const project = projectsStore.projectById(projectId)
 return project?.name || projectId.slice(0, 8)
}
</script>
<template>
 <div class="space-y-6 max-w-[1600px] mx-auto pb-10">
 <!-- Header Area -->
 <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 py-2">
 <div class="space-y-1">
 <h1 class="text-3xl font-bold tracking-tight text-foreground">
 任务管理
 </h1>
 <p class="text-muted-foreground text-sm">
 全自动 AI 开发任务编排与监控中心
 </p>
 </div>
 <!-- Stats Cards (Compact) -->
 <div class="flex gap-3">
 <div class="flex items-center gap-3 px-4 py-2 bg-card rounded-lg border shadow-sm">
 <div class=".5 rounded-full bg-amber-500/10 text-amber-500">
 <span class="icon-[lucide--zap] w-4 " />
 </div>
 <div class="flex flex-col">
 <span class="text-xs text-muted-foreground">进行中</span>
 <span class="text-lg font-bold leading-none">{{ tasksStore.stats.running }}</span>
 </div>
 </div>
 <div class="flex items-center gap-3 px-4 py-2 bg-card rounded-lg border shadow-sm">
 <div class=".5 rounded-full bg-blue-500/10 text-blue-500">
 <span class="icon-[lucide--eye] w-4 " />
 </div>
 <div class="flex flex-col">
 <span class="text-xs text-muted-foreground">待审核</span>
 <span class="text-lg font-bold leading-none">{{ tasksStore.stats.review }}</span>
 </div>
 </div>
 <div class="flex items-center gap-3 px-4 py-2 bg-card rounded-lg border shadow-sm">
 <div class=".5 rounded-full bg-emerald-500/10 text-emerald-500">
 <span class="icon-[lucide--check-circle] w-4 " />
 </div>
 <div class="flex flex-col">
 <span class="text-xs text-muted-foreground">已完成</span>
 <span class="text-lg font-bold leading-none">{{ tasksStore.stats.completed }}</span>
 </div>
 </div>
 </div>
 </div>
 <!-- Controls Bar -->
 <div class="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between bg-card/50 rounded-xl">
 <div class="flex items-center gap-2 w-full sm:w-auto">
 <!-- Project Filter -->
 <Select v-model="projectFilter">
 <SelectTrigger class="w-full sm:w-[200px] bg-background border-input hover:bg-accent/50 transition-colors">
 <div class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--folder-git-2] w-4 " />
 <span class="text-foreground"><SelectValue placeholder="所有项目" /></span>
 </div>
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
 <!-- Status Filter -->
 <Select v-model="statusFilter">
 <SelectTrigger class="w-full sm:w-[160px] bg-background border-input hover:bg-accent/50 transition-colors">
 <div class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--list-filter] w-4 " />
 <span class="text-foreground"><SelectValue placeholder="所有状态" /></span>
 </div>
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
 <Button variant="ghost" size="sm" class="text-muted-foreground hover:text-foreground" @click="fetchTasks">
 <span class="icon-[lucide--refresh-cw] w-4 mr-2" />
 刷新列表
 </Button>
 </div>
 <!-- Loading State -->
 <div v-if="loading" class="space-y-4">
 <div v-for="i in 5":key="i" class=" w-full rounded-xl border bg-card/50 animate-pulse" />
 </div>
 <!-- Empty State -->
 <div
 v-else-if="tasksStore.tasks.length === 0"
 class="flex flex-col items-center justify-center py-20 text-center border-2 border-dashed border-muted rounded-xl bg-muted/5"
 >
 <div class=" rounded-full bg-muted mb-4">
 <span class="icon-[lucide--clipboard-list] w-8 text-muted-foreground" />
 </div>
 <h3 class="text-lg font-semibold">
 暂无任务
 </h3>
 <p class="text-sm text-muted-foreground mt-2 max-w-sm">
 当前过滤条件下没有找到任务。任务通常由外部 Webhook 触发自动创建。
 </p>
 <Button
 v-if="projectFilter !== '__all__' || statusFilter !== '__all__'"
 variant="outline"
 class="mt-6"
 @click=" => { projectFilter = '__all__'; statusFilter = '__all__' }"
 >
 清除筛选
 </Button>
 </div>
 <!-- Task List -->
 <div v-else class="grid gap-3">
 <RouterLink
 v-for="task in tasksStore.tasks":key="task.id":to="`/tasks/${task.id}`"
 class="group relative flex flex-col sm:flex-row sm:items-center gap-4 rounded-xl border bg-card hover:border-primary/50 hover:shadow-md hover:shadow-primary/5 transition-all duration-200"
 >
 <!-- Status Line (Left Border Accent) -->
 <div
 class="absolute left-0 top-3 bottom-3 w-1 rounded-r-full transition-colors":class="{
 'bg-slate-300': task.status === 'pending',
 'bg-indigo-500': task.status === 'planning',
 'bg-blue-500': task.status === 'plan_review',
 'bg-amber-500': task.status === 'executing',
 'bg-purple-500': task.status === 'code_review',
 'bg-emerald-500': task.status === 'merged',
 'bg-red-500': task.status === 'failed',
 }"
 />
 <!-- Main Content -->
 <div class="flex-1 min-w-0 ml-3 space-y-1">
 <div class="flex items-start justify-between gap-4">
 <h3 class="font-semibold text-base truncate pr-4 group-hover:text-primary transition-colors">
 {{ task.title }}
 </h3>
 <span class="icon-[lucide--chevron-right] w-5 text-muted-foreground/30 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300 sm:block hidden" />
 </div>
 <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
 <!-- Project Badge -->
 <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-muted/50 text-xs font-medium group-hover:bg-muted transition-colors">
 <span class="icon-[lucide--folder] w-3 " />
 {{ getProjectName(task.project_id) }}
 </div>
 <!-- Time -->
 <div class="flex items-center gap-1.5 text-xs">
 <span class="icon-[lucide--clock] w-3 " />
 {{ formatDate(task.created_at) }}
 </div>
 <!-- ID (Subtle) -->
 <div class="text-xs opacity-50 font-mono">
 #{{ task.id.slice(0, 8) }}
 </div>
 </div>
 </div>
 <!-- Right Side: Status -->
 <div class="flex items-center justify-between sm:justify-end gap-4 ml-3 sm:ml-0 mt-2 sm:mt-0">
 <TaskStatusBadge:status="task.status":show-icon="true" />
 </div>
 </RouterLink>
 </div>
 <!-- Footer Stats -->
 <div v-if="tasksStore.tasks.length > 0" class="flex justify-center pt-6">
 <span class="text-xs text-muted-foreground bg-muted/50 px-3 py-1 rounded-full">
 显示 {{ tasksStore.tasks.length }} 个任务 / 共 {{ tasksStore.taskCount }} 个
 </span>
 </div>
 </div>
</template>
