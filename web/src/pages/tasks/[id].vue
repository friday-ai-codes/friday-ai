<script setup lang="ts">
import type { TaskStatus } from '~/types'
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Separator } from '~/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { STATUS_LABELS, VALID_TRANSITIONS } from '~/types'
const route = useRoute
const router = useRouter
const tasksStore = useTasksStore
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
const taskId = computed( => route.params.id as string)
useHead({
 title: computed( => tasksStore.currentTask?.title
 ? `${tasksStore.currentTask.title} - Friday AI`: '任务详情 - Friday AI'),
})
// 加载数据
const loading = ref(true)
onMounted(async => {
 try {
 await tasksStore.fetchTask(taskId.value)
 if (tasksStore.currentTask) {
 await projectsStore.fetchProject(tasksStore.currentTask.project_id)
 }
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取任务详情')
 }
 finally {
 loading.value = false
 }
})
// 任务和项目
const task = computed( => tasksStore.currentTask)
const project = computed( => projectsStore.currentProject)
// 仓库选择
const selectedRepoId = ref('')
const updatingRepo = ref(false)
async function handleUpdateRepo {
 if (!task.value || !selectedRepoId.value)
 return
 updatingRepo.value = true
 try {
 await tasksStore.updateTask(task.value.id, {
 repository_id: selectedRepoId.value,
 })
 success('仓库已更新', '任务关联仓库已更新')
 // 重新获取任务信息
 await tasksStore.fetchTask(task.value.id)
 }
 catch (e) {
 showError('更新失败', e instanceof Error ? e.message: '无法更新任务仓库')
 }
 finally {
 updatingRepo.value = false
 }
}
// 当项目加载完成后，如果任务已有仓库，设置选中值
watch( => task.value?.repository_id, (newId) => {
 if (newId) {
 selectedRepoId.value = newId
 }
}, { immediate: true })
// 日志轮询
const { isPolling, start: startPolling, stop: stopPolling } = usePolling(async => {
 if (task.value) {
 await tasksStore.fetchLogs(task.value.id)
 await tasksStore.fetchContainerStatus(task.value.id)
 }
}, { interval: 2000, immediate: false })
// 当任务正在运行时自动开始轮询
watch( => task.value?.status, (status) => {
 if (status === 'planning' || status === 'executing') {
 startPolling
 }
 else {
 stopPolling
 }
}, { immediate: true })
// 可用的状态转换
const availableTransitions = computed( => {
 if (!task.value)
 return
 return VALID_TRANSITIONS[task.value.status] ||
})
// 状态转换
const transitioning = ref(false)
async function handleTransition(newStatus: TaskStatus) {
 if (!task.value)
 return
 transitioning.value = true
 try {
 await tasksStore.transitionTask(task.value.id, newStatus)
 success('状态已更新', `任务已转换为 ${STATUS_LABELS[newStatus]}`)
 }
 catch (e) {
 showError('转换失败', e instanceof Error ? e.message: '无法转换任务状态')
 }
 finally {
 transitioning.value = false
 }
}
// 执行任务
const executing = ref(false)
async function handleExecute(mode: 'plan' | 'execute') {
 if (!task.value)
 return
 executing.value = true
 try {
 const response = await tasksStore.executeTask(task.value.id, mode)
 success('任务已启动', `容器 ID: ${response.container_id}`)
 startPolling
 }
 catch (e) {
 showError('启动失败', e instanceof Error ? e.message: '无法启动任务')
 }
 finally {
 executing.value = false
 }
}
// 停止任务
const stopping = ref(false)
const stopDialogOpen = ref(false)
async function handleStop {
 if (!task.value)
 return
 stopping.value = true
 try {
 await tasksStore.stopTask(task.value.id)
 success('任务已停止')
 stopDialogOpen.value = false
 }
 catch (e) {
 showError('停止失败', e instanceof Error ? e.message: '无法停止任务')
 }
 finally {
 stopping.value = false
 }
}
// 删除任务
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 if (!task.value)
 return
 deleting.value = true
 try {
 await tasksStore.deleteTask(task.value.id)
 success('删除成功', '任务已删除')
 router.push('/tasks')
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除任务')
 }
 finally {
 deleting.value = false
 deleteDialogOpen.value = false
 }
}
// 格式化日期
function formatDate(dateStr: string | null) {
 if (!dateStr)
 return '-'
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 状态步骤
const statusSteps = ['pending', 'planning', 'plan_review', 'executing', 'code_review', 'merged'] as const
const currentStepIndex = computed( => {
 if (!task.value)
 return -1
 if (task.value.status === 'failed')
 return -1
 return statusSteps.indexOf(task.value.status as typeof statusSteps[number])
})
// 是否正在运行
const isRunning = computed( =>
 task.value?.status === 'planning' || task.value?.status === 'executing',
)
// 日志内容
const logs = computed( => tasksStore.currentLogs)
</script>
<template>
 <div class="max-w-[1600px] mx-auto pb-10 space-y-6">
 <!-- Breadcrumb & Back -->
 <nav class="flex items-center text-sm text-muted-foreground">
 <RouterLink to="/tasks" class="hover:text-foreground transition-colors flex items-center">
 <span class="icon-[lucide--arrow-left] mr-1 w-4 " />
 返回列表
 </RouterLink>
 <span class="mx-2 text-muted-foreground/30">/</span>
 <span class="text-foreground truncate max-w-[200px]">{{ task?.title || '任务详情' }}</span>
 </nav>
 <!-- Loading State -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <template v-else-if="task">
 <!-- Top Header Area -->
 <div class="flex flex-col lg:flex-row lg:items-start justify-between gap-6 pb-6 border-b border-border/50">
 <div class="space-y-4 flex-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-primary/10 text-primary">
 <span class="icon-[lucide--hash] w-6 " />
 </div>
 <h1 class="text-3xl font-bold tracking-tight text-foreground">{{ task.title }}</h1>
 </div>
 <div class="flex flex-wrap items-center gap-4 text-sm">
 <TaskStatusBadge:status="task.status":show-icon="true" class="text-sm px-3 py-1" />
 <div class="w-px bg-border" />
 <div class="flex items-center text-muted-foreground gap-1.5">
 <span class="icon-[lucide--folder-git-2] w-4 " />
 <span>{{ project?.name }}</span>
 </div>
 <div class="w-px bg-border" />
 <div class="flex items-center text-muted-foreground gap-1.5">
 <span class="icon-[lucide--calendar] w-4 " />
 <span>创建于 {{ formatDate(task.created_at) }}</span>
 </div>
 </div>
 </div>
 <!-- Primary Actions -->
 <div class="flex flex-wrap items-center gap-3">
 <Button
 v-if="task.status === 'pending'"
 size="lg":disabled="executing || !task.repository_id":class="!task.repository_id ? 'opacity-50': 'shadow-lg shadow-primary/20'"
 @click="handleExecute('plan')"
 >
 <span v-if="executing" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--rocket] mr-2" />
 启动规划
 </Button>
 <Button
 v-if="task.status === 'plan_review'"
 size="lg":disabled="executing"
 class="shadow-lg shadow-primary/20"
 @click="handleExecute('execute')"
 >
 <span v-if="executing" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--play] mr-2" />
 执行任务
 </Button>
 <Button v-if="isRunning" variant="destructive" size="lg" @click="stopDialogOpen = true">
 <span class="icon-[lucide--square] mr-2" />
 停止
 </Button>
 <Button v-if="!isRunning" variant="outline" size="icon" class="w-10 " @click="deleteDialogOpen = true" title="删除任务">
 <span class="icon-[lucide--trash-2] w-4 text-destructive" />
 </Button>
 </div>
 </div>
 <!-- Warning: Missing Repo -->
 <div v-if="!task.repository_id" class=" rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/50 flex flex-col sm:flex-row items-start gap-4">
 <div class=" rounded-full bg-amber-100 dark:bg-amber-900/50 text-amber-600 dark:text-amber-400">
 <span class="icon-[lucide--alert-triangle] w-5 " />
 </div>
 <div class="flex-1 space-y-3">
 <div>
 <h3 class="font-medium text-amber-900 dark:text-amber-100">未关联 Git 仓库</h3>
 <p class="text-sm text-amber-700 dark:text-amber-300/70">请选择一个代码仓库以开始执行任务。</p>
 </div>
 <div class="flex items-center gap-3">
 <Select v-model="selectedRepoId">
 <SelectTrigger class="w-[280px] bg-background border-amber-200 dark:border-amber-800">
 <SelectValue placeholder="选择仓库..." />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="repo in project?.repositories || ":key="repo.id":value="repo.id">
 {{ repo.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Button:disabled="!selectedRepoId || updatingRepo" @click="handleUpdateRepo" size="sm" variant="secondary">
 <span v-if="updatingRepo" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 关联仓库
 </Button>
 </div>
 </div>
 </div>
 <!-- Main Layout Grid -->
 <div class="grid grid-cols-1 xl:grid-cols-3 gap-8">
 <!-- Left Column: Content (2/3 width) -->
 <div class="xl:col-span-2 space-y-8">
 <!-- Progress Timeline -->
 <div class="relative pt-2 pb-6">
 <!-- Line -->
 <div class="absolute top-5 left-0 right-0 .5 bg-muted -z-10"></div>
 <!-- Steps -->
 <div class="flex justify-between">
 <div
 v-for="(step, index) in statusSteps":key="step"
 class="flex flex-col items-center gap-2 group relative bg-background px-2"
 >
 <div
 class="w-10 rounded-full border-2 flex items-center justify-center transition-all duration-300":class="[
 index < currentStepIndex ? 'bg-primary border-primary text-primary-foreground':
 index === currentStepIndex ? 'bg-background border-primary text-primary ring-4 ring-primary/10':
 'bg-background border-muted text-muted-foreground'
 ]"
 >
 <span v-if="index < currentStepIndex" class="icon-[lucide--check] w-5 " />
 <span v-else-if="index === currentStepIndex && isRunning" class="icon-[lucide--loader-circle] w-5 animate-spin" />
 <span v-else class="text-sm font-medium">{{ index + 1 }}</span>
 </div>
 <span
 class="text-xs font-medium transition-colors duration-300":class="index <= currentStepIndex ? 'text-foreground': 'text-muted-foreground'"
 >
 {{ STATUS_LABELS[step] }}
 </span>
 </div>
 </div>
 <!-- Error Alert -->
 <div v-if="task.status === 'failed'" class="mt-6 mx-auto max-w-lg rounded-xl bg-destructive/5 border border-destructive/20 text-center">
 <div class="inline-flex rounded-full bg-destructive/10 text-destructive mb-2">
 <span class="icon-[lucide--x-circle] w-6 " />
 </div>
 <h3 class="font-semibold text-destructive">任务执行失败</h3>
 <p class="text-sm text-destructive/80 mt-1 mb-3">{{ task.error_message || '未知错误' }}</p>
 <Button variant="outline" size="sm" class="border-destructive/30 hover:bg-destructive/10 text-destructive" @click="handleTransition('pending')">
 <span class="icon-[lucide--rotate-ccw] mr-2" /> 重试任务
 </Button>
 </div>
 </div>
 <!-- Tabs: Plan & Logs -->
 <Tabs default-value="plan" class="w-full">
 <div class="flex items-center justify-between mb-4">
 <TabsList class="bg-muted/50 ">
 <TabsTrigger value="plan" class="data-[state=active]:bg-background data-[state=active]:shadow-sm">
 <span class="icon-[lucide--file-code] mr-2 w-4 " />
 执行方案
 </TabsTrigger>
 <TabsTrigger value="logs" class="data-[state=active]:bg-background data-[state=active]:shadow-sm">
 <span class="icon-[lucide--terminal-square] mr-2 w-4 " />
 运行日志
 <span v-if="isPolling" class="ml-2 w-1.5 .5 rounded-full bg-green-500 animate-pulse" />
 </TabsTrigger>
 </TabsList>
 <!-- Log Actions -->
 <div class="flex items-center gap-2">
 <Button v-if="isPolling" size="sm" variant="ghost" class=" text-xs text-muted-foreground" @click="stopPolling">
 <span class="icon-[lucide--pause] mr-1 w-3 " /> 暂停刷新
 </Button>
 <Button v-if="!isPolling && isRunning" size="sm" variant="ghost" class=" text-xs text-primary" @click="startPolling">
 <span class="icon-[lucide--play] mr-1 w-3 " /> 恢复刷新
 </Button>
 </div>
 </div>
 <TabsContent value="plan" class="mt-0 outline-none">
 <div class="rounded-xl border bg-card shadow-sm min-h-[400px]">
 <div v-if="task.plan_output" class="">
 <div class="prose prose-sm dark:prose-invert max-w-none">
 <pre class="bg-muted/30 rounded-lg overflow-x-auto text-sm font-mono leading-relaxed border border-border/50">{{ task.plan_output }}</pre>
 </div>
 </div>
 <div v-else class="flex flex-col items-center justify-center h-[400px] text-muted-foreground">
 <span class="icon-[lucide--bot] w-12 mb-4 opacity-20" />
 <p>等待 AI 生成执行方案...</p>
 </div>
 </div>
 <!-- Human Feedback -->
 <div v-if="task.human_feedback" class="mt-6 rounded-xl border border-blue-200 bg-blue-50/50 dark:bg-blue-950/10 dark:border-blue-800 ">
 <h4 class="font-medium text-blue-900 dark:text-blue-100 flex items-center gap-2 mb-2">
 <span class="icon-[lucide--message-square] w-4 " /> 人工反馈
 </h4>
 <p class="text-sm text-blue-800 dark:text-blue-200/80">{{ task.human_feedback }}</p>
 </div>
 </TabsContent>
 <TabsContent value="logs" class="mt-0 outline-none">
 <div class="rounded-xl border bg-[#1e1e1e] shadow-inner min-h-[500px] flex flex-col">
 <div class="flex items-center justify-between px-4 py-2 border-b border-white/10 bg-white/5">
 <div class="flex items-center gap-2">
 <div class="flex gap-1.5">
 <div class="w-2.5 .5 rounded-full bg-red-500/50" />
 <div class="w-2.5 .5 rounded-full bg-yellow-500/50" />
 <div class="w-2.5 .5 rounded-full bg-green-500/50" />
 </div>
 <span class="text-xs text-white/40 font-mono ml-2">Console Output</span>
 </div>
 <div v-if="tasksStore.containerStatus?.container" class="flex gap-2">
 <span class="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/60 font-mono">
 ID: {{ tasksStore.containerStatus.container.id?.slice(0, 8) }}
 </span>
 <span class="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/60 font-mono">
 {{ tasksStore.containerStatus.container.status }}
 </span>
 </div>
 </div>
 <div class="flex-1 overflow-auto font-mono text-xs text-gray-300 leading-relaxed scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
 <pre v-if="logs" class="whitespace-pre-wrap">{{ logs }}</pre>
 <div v-else class="flex flex-col items-center justify-center h-full text-white/20">
 <span class="icon-[lucide--terminal] w-12 mb-4" />
 <p>等待日志输出...</p>
 </div>
 </div>
 </div>
 </TabsContent>
 </Tabs>
 </div>
 <!-- Right Column: Sidebar (1/3 width) -->
 <div class="space-y-6">
 <!-- Details Card -->
 <div class="rounded-xl border bg-card shadow-sm overflow-hidden">
 <div class="px-4 py-3 border-b bg-muted/30">
 <h3 class="font-medium text-sm">基本信息</h3>
 </div>
 <div class=" space-y-4">
 <div class="grid grid-cols-1 gap-4 text-sm">
 <div>
 <span class="text-muted-foreground block mb-1">任务 ID</span>
 <span class="font-mono text-xs bg-muted/50 px-2 py-1 rounded">{{ task.id }}</span>
 </div>
 <div>
 <span class="text-muted-foreground block mb-1">描述</span>
 <p class="text-foreground leading-relaxed">{{ task.description || '暂无描述' }}</p>
 </div>
 <div class="grid grid-cols-2 gap-4">
 <div>
 <span class="text-muted-foreground block mb-1">工作项 ID</span>
 <span class="font-mono text-xs">{{ task.work_item_id }}</span>
 </div>
 <div>
 <span class="text-muted-foreground block mb-1">功能 ID</span>
 <span class="font-mono text-xs">{{ task.feature_id }}</span>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- Git Info Card -->
 <div class="rounded-xl border bg-card shadow-sm overflow-hidden">
 <div class="px-4 py-3 border-b bg-muted/30 flex justify-between items-center">
 <h3 class="font-medium text-sm">Git 信息</h3>
 <span class="icon-[lucide--git-branch] w-4 text-muted-foreground" />
 </div>
 <div class=" space-y-4 text-sm">
 <div class="flex items-center justify-between">
 <span class="text-muted-foreground">仓库</span>
 <span class="font-medium">{{ project?.repositories?.find(r => r.id === task?.repository_id)?.name || '-' }}</span>
 </div>
 <div class="flex items-center justify-between">
 <span class="text-muted-foreground">基础分支</span>
 <span class="font-mono text-xs bg-muted/50 px-1.5 py-0.5 rounded text-muted-foreground">{{ task?.git_branch || 'main' }}</span>
 </div>
 <div class="flex items-center justify-between">
 <span class="text-muted-foreground">功能分支</span>
 <span class="font-mono text-xs text-primary">{{ task.branch_name || '-' }}</span>
 </div>
 <div v-if="task.pr_url" class="pt-2 border-t">
 <a:href="task.pr_url" target="_blank" class="flex items-center justify-center gap-2 w-full py-2 rounded-lg bg-blue-50 text-blue-600 hover:bg-blue-100 dark:bg-blue-900/20 dark:text-blue-400 transition-colors">
 <span class="icon-[lucide--git-pull-request] w-4 " />
 查看 Pull Request
 </a>
 </div>
 </div>
 </div>
 <!-- Manual Actions Card -->
 <div v-if="availableTransitions.length > 0" class="rounded-xl border bg-card shadow-sm overflow-hidden">
 <div class="px-4 py-3 border-b bg-muted/30">
 <h3 class="font-medium text-sm">手动状态流转</h3>
 </div>
 <div class="">
 <div class="flex flex-wrap gap-2">
 <Button
 v-for="status in availableTransitions":key="status"
 variant="secondary"
 size="sm"
 class="flex-1":disabled="transitioning"
 @click="handleTransition(status)"
 >
 {{ STATUS_LABELS[status] }}
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
 </template>
 <!-- Empty State -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="任务不存在"
 description="未找到该任务，可能已被删除"
 action-label="返回列表"
 @action="router.push('/tasks')"
 />
 <!-- Dialogs -->
 <ConfirmDialog
 v-model:open="stopDialogOpen"
 title="停止任务"
 description="确定要停止此任务吗？正在执行的容器将被终止。"
 confirm-text="停止"
 variant="destructive":loading="stopping"
 @confirm="handleStop"
 />
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除任务"
 description="确定要删除此任务吗？此操作不可撤销。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
</template>
