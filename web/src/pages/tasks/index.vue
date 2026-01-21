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
import { STATUS_LABELS } from '~/types'
useHead({
 title: '任务列表 - Friday AI',
})
const route = useRoute
const tasksStore = useTasksStore
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
 <div class="space-y-8">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/10">
 <span class="icon-[lucide--list-checks] text-2xl text-amber-500" />
 </div>
 <h1 class="text-2xl font-bold">任务管理</h1>
 </div>
 <p class="text-muted-foreground ml-12">
 查看和管理 AI 开发任务
 </p>
 </div>
 </div>
 <!-- 过滤器和统计 -->
 <div class="flex flex-col md:flex-row gap-4 md:items-center md:justify-between">
 <!-- 过滤器 -->
 <div class="flex flex-wrap items-center gap-3">
 <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 text-sm text-muted-foreground">
 <span class="icon-[lucide--filter]" />
 <span>筛选</span>
 </div>
 <!-- 项目过滤 -->
 <Select v-model="projectFilter">
 <SelectTrigger class="w-44 bg-card/50 border-border/50">
 <SelectValue placeholder="选择项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__all__">全部项目</SelectItem>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 状态过滤 -->
 <Select v-model="statusFilter">
 <SelectTrigger class="w-36 bg-card/50 border-border/50">
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
 <!-- 刷新按钮 -->
 <Button variant="outline" size="icon" class=" w-9" @click="fetchTasks">
 <span class="icon-[lucide--refresh-cw]" />
 </Button>
 </div>
 <!-- 统计信息 -->
 <div class="flex items-center gap-4 text-sm">
 <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-600">
 <span class="icon-[lucide--zap]" />
 <span>运行中 {{ tasksStore.stats.running }}</span>
 </div>
 <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-500/10 text-blue-600">
 <span class="icon-[lucide--eye]" />
 <span>待审核 {{ tasksStore.stats.review }}</span>
 </div>
 <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-600">
 <span class="icon-[lucide--check-circle]" />
 <span>已完成 {{ tasksStore.stats.completed }}</span>
 </div>
 </div>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="tasksStore.tasks.length === 0"
 icon="lucide--list-checks"
 title="暂无任务"
 description="任务通常由飞书 Webhook 自动创建"
 gradient="from-amber-500/20 to-orange-500/20"
 />
 <!-- 任务列表 -->
 <div v-else class="space-y-3">
 <RouterLink
 v-for="(task, index) in tasksStore.tasks":key="task.id":to="`/tasks/${task.id}`"
 class="group block"
 >
 <div class="relative rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all duration-300">
 <div class="flex items-center gap-4">
 <!-- 序号 -->
 <div class="flex-shrink-0 w-10 rounded-xl bg-gradient-to-br from-muted to-muted/50 flex items-center justify-center font-medium text-muted-foreground group-hover:from-primary/20 group-hover:to-primary/10 group-hover:text-primary transition-all duration-300">
 {{ index + 1 }}
 </div>
 <!-- 内容 -->
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-3 mb-1">
 <h3 class="font-semibold truncate group-hover:text-primary transition-colors">
 {{ task.title }}
 </h3>
 <TaskStatusBadge:status="task.status":show-icon="true" />
 </div>
 <div class="flex items-center gap-4 text-sm text-muted-foreground">
 <span class="flex items-center gap-1">
 <span class="icon-[lucide--folder]" />
 {{ getProjectName(task.project_id) }}
 </span>
 <span class="flex items-center gap-1">
 <span class="icon-[lucide--clock]" />
 {{ formatDate(task.created_at) }}
 </span>
 </div>
 </div>
 <!-- 箭头 -->
 <span class="icon-[lucide--chevron-right] text-xl text-muted-foreground/30 group-hover:text-primary group-hover:translate-x-1 transition-all" />
 </div>
 </div>
 </RouterLink>
 </div>
 <!-- 底部统计 -->
 <div v-if="tasksStore.tasks.length > 0" class="flex items-center justify-center">
 <div class="text-sm text-muted-foreground px-4 py-2 rounded-full bg-muted/30">
 共 {{ tasksStore.taskCount }} 个任务
 </div>
 </div>
 </div>
</template>
