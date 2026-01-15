<script setup lang="ts">
import type { TaskStatus } from '~/types'
import { useHead } from '@vueuse/head'
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
import { STATUS_LABELS } from '~/types'
useHead({
 title: '任务列表 - Friday AI',
})
const route = useRoute
const tasksStore = useTasksStore
const projectsStore = useProjectsStore
const { error: showError } = useToast
// 从 URL 获取过滤参数
const projectFilter = ref<string>(route.query.project_id as string || '')
const statusFilter = ref<string>(route.query.status as string || '')
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
 await tasksStore.fetchTasks({
 project_id: projectFilter.value || undefined,
 status: (statusFilter.value as TaskStatus) || undefined,
 })
}
// 监听过滤条件变化
watch([projectFilter, statusFilter], => {
 fetchTasks
})
// 状态选项
const statusOptions: { value: string, label: string } = [
 { value: '', label: '全部状态' },
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
 <div class="space-y-6">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div>
 <h1 class="text-2xl font-bold">
 任务管理
 </h1>
 <p class="text-muted-foreground">
 查看和管理 AI 开发任务
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
 <!-- 状态过滤 -->
 <div class="w-40">
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
 <Button variant="outline" size="icon" @click="fetchTasks">
 <span class="icon-[lucide--refresh-cw]" />
 </Button>
 </div>
 </CardContent>
 </Card>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="tasksStore.tasks.length === 0"
 icon="lucide--list-checks"
 title="暂无任务"
 description="任务通常由飞书 Webhook 自动创建"
 />
 <!-- 任务表格 -->
 <Card v-else>
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead class="w-[300px]">
 任务名称
 </TableHead>
 <TableHead>项目</TableHead>
 <TableHead>状态</TableHead>
 <TableHead>创建时间</TableHead>
 <TableHead class="text-right">
 操作
 </TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <TableRow
 v-for="task in tasksStore.tasks":key="task.id"
 class="cursor-pointer hover:bg-muted/50"
 @click="$router.push(`/tasks/${task.id}`)"
 >
 <TableCell class="font-medium">
 <div class="max-w-[280px] truncate":title="task.title">
 {{ task.title }}
 </div>
 </TableCell>
 <TableCell>
 <span class="text-muted-foreground">
 {{ getProjectName(task.project_id) }}
 </span>
 </TableCell>
 <TableCell>
 <TaskStatusBadge:status="task.status":show-icon="true" />
 </TableCell>
 <TableCell class="text-muted-foreground">
 {{ formatDate(task.created_at) }}
 </TableCell>
 <TableCell class="text-right">
 <RouterLink:to="`/tasks/${task.id}`" @click.stop>
 <Button variant="ghost" size="sm">
 <span class="icon-[lucide--arrow-right]" />
 </Button>
 </RouterLink>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </Card>
 <!-- 统计信息 -->
 <div class="flex items-center justify-between text-sm text-muted-foreground">
 <span>共 {{ tasksStore.taskCount }} 个任务</span>
 <div class="flex gap-4">
 <span>运行中: {{ tasksStore.stats.running }}</span>
 <span>待审核: {{ tasksStore.stats.review }}</span>
 <span>已完成: {{ tasksStore.stats.completed }}</span>
 </div>
 </div>
 </div>
</template>
