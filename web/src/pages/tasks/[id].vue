<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Separator } from '~/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import type { TaskStatus } from '~/types'
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
 } catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取任务详情')
 } finally {
 loading.value = false
 }
})
// 任务和项目
const task = computed( => tasksStore.currentTask)
const project = computed( => projectsStore.currentProject)
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
 } else {
 stopPolling
 }
}, { immediate: true })
// 可用的状态转换
const availableTransitions = computed( => {
 if (!task.value) return
 return VALID_TRANSITIONS[task.value.status] ||
})
// 状态转换
const transitioning = ref(false)
async function handleTransition(newStatus: TaskStatus) {
 if (!task.value) return
 transitioning.value = true
 try {
 await tasksStore.transitionTask(task.value.id, newStatus)
 success('状态已更新', `任务已转换为 ${STATUS_LABELS[newStatus]}`)
 } catch (e) {
 showError('转换失败', e instanceof Error ? e.message: '无法转换任务状态')
 } finally {
 transitioning.value = false
 }
}
// 执行任务
const executing = ref(false)
async function handleExecute(mode: 'plan' | 'execute') {
 if (!task.value) return
 executing.value = true
 try {
 const response = await tasksStore.executeTask(task.value.id, mode)
 success('任务已启动', `容器 ID: ${response.container_id}`)
 startPolling
 } catch (e) {
 showError('启动失败', e instanceof Error ? e.message: '无法启动任务')
 } finally {
 executing.value = false
 }
}
// 停止任务
const stopping = ref(false)
const stopDialogOpen = ref(false)
async function handleStop {
 if (!task.value) return
 stopping.value = true
 try {
 await tasksStore.stopTask(task.value.id)
 success('任务已停止')
 stopDialogOpen.value = false
 } catch (e) {
 showError('停止失败', e instanceof Error ? e.message: '无法停止任务')
 } finally {
 stopping.value = false
 }
}
// 删除任务
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 if (!task.value) return
 deleting.value = true
 try {
 await tasksStore.deleteTask(task.value.id)
 success('删除成功', '任务已删除')
 router.push('/tasks')
 } catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除任务')
 } finally {
 deleting.value = false
 deleteDialogOpen.value = false
 }
}
// 格式化日期
function formatDate(dateStr: string | null) {
 if (!dateStr) return '-'
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 状态步骤
const statusSteps = ['pending', 'planning', 'plan_review', 'executing', 'code_review', 'merged'] as const
const currentStepIndex = computed( => {
 if (!task.value) return -1
 if (task.value.status === 'failed') return -1
 return statusSteps.indexOf(task.value.status as typeof statusSteps[number])
})
// 是否正在运行
const isRunning = computed( =>
 task.value?.status === 'planning' || task.value?.status === 'executing'
)
// 日志内容
const logs = computed( => tasksStore.currentLogs)
</script>
<template>
 <div class="space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/tasks" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 <span class="icon-[lucide--arrow-left] mr-1"></span>
 返回任务列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 任务详情 -->
 <template v-else-if="task">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div class="space-y-2">
 <h1 class="text-2xl font-bold">{{ task.title }}</h1>
 <div class="flex items-center gap-3">
 <TaskStatusBadge:status="task.status":show-icon="true" />
 <span class="text-muted-foreground">
 {{ project?.name || task.project_id.slice(0, 8) }}
 </span>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <!-- 执行按钮 -->
 <Button
 v-if="task.status === 'pending'":disabled="executing"
 @click="handleExecute('plan')"
 >
 <span v-if="executing" class="icon-[lucide--loader-circle] mr-2 animate-spin"></span>
 <span v-else class="icon-[lucide--rocket] mr-2"></span>
 启动规划
 </Button>
 <Button
 v-if="task.status === 'plan_review'":disabled="executing"
 @click="handleExecute('execute')"
 >
 <span v-if="executing" class="icon-[lucide--loader-circle] mr-2 animate-spin"></span>
 <span v-else class="icon-[lucide--play] mr-2"></span>
 执行任务
 </Button>
 <!-- 停止按钮 -->
 <Button
 v-if="isRunning"
 variant="destructive"
 @click="stopDialogOpen = true"
 >
 <span class="icon-[lucide--square] mr-2"></span>
 停止
 </Button>
 <!-- 删除按钮 -->
 <Button
 v-if="!isRunning"
 variant="outline"
 @click="deleteDialogOpen = true"
 >
 <span class="icon-[lucide--trash-2] mr-2"></span>
 删除
 </Button>
 </div>
 </div>
 <!-- 状态步骤条 -->
 <Card>
 <CardContent class="pt-6">
 <div class="flex items-center justify-between">
 <template v-for="(step, index) in statusSteps":key="step">
 <div class="flex flex-col items-center gap-2">
 <div:class="[
 'w-10 rounded-full flex items-center justify-center text-lg',
 index <= currentStepIndex
 ? 'bg-primary text-primary-foreground': 'bg-muted text-muted-foreground',
 task.status === 'failed' && 'bg-red-500 text-white'
 ]"
 >
 <span v-if="index < currentStepIndex" class="icon-[lucide--check]"></span>
 <span v-else>{{ index + 1 }}</span>
 </div>
 <span class="text-xs text-muted-foreground">
 {{ STATUS_LABELS[step] }}
 </span>
 </div>
 <div
 v-if="index < statusSteps.length - 1":class="[
 'flex-1 mx-2',
 index < currentStepIndex ? 'bg-primary': 'bg-muted'
 ]"
 ></div>
 </template>
 </div>
 <!-- 失败状态提示 -->
 <div v-if="task.status === 'failed'" class="mt-4 rounded-lg bg-red-50 text-red-800">
 <p class="font-medium flex items-center gap-2">
 <span class="icon-[lucide--x-circle]"></span>
 任务执行失败
 </p>
 <p v-if="task.error_message" class="text-sm mt-1">{{ task.error_message }}</p>
 <Button
 class="mt-2"
 size="sm"
 variant="outline":disabled="transitioning"
 @click="handleTransition('pending')"
 >
 <span class="icon-[lucide--rotate-ccw] mr-1"></span>
 重试任务
 </Button>
 </div>
 </CardContent>
 </Card>
 <Tabs default-value="info" class="w-full">
 <TabsList>
 <TabsTrigger value="info">
 <span class="icon-[lucide--info] mr-1"></span>
 基本信息
 </TabsTrigger>
 <TabsTrigger value="plan">
 <span class="icon-[lucide--file-text] mr-1"></span>
 执行方案
 </TabsTrigger>
 <TabsTrigger value="logs">
 <span class="icon-[lucide--terminal] mr-1"></span>
 运行日志
 <span v-if="isPolling" class="ml-1 w-2 rounded-full bg-green-500 animate-pulse"></span>
 </TabsTrigger>
 <TabsTrigger value="git">
 <span class="icon-[lucide--git-branch] mr-1"></span>
 Git 信息
 </TabsTrigger>
 </TabsList>
 <!-- 基本信息 -->
 <TabsContent value="info" class="mt-4">
 <div class="grid gap-4 md:grid-cols-2">
 <Card>
 <CardHeader>
 <CardTitle>任务信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div>
 <label class="text-sm text-muted-foreground">任务 ID</label>
 <p class="font-mono text-sm">{{ task.id }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">工作项 ID</label>
 <p class="font-mono text-sm">{{ task.work_item_id }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">功能 ID</label>
 <p class="font-mono text-sm">{{ task.feature_id }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">描述</label>
 <p class="text-sm mt-1">{{ task.description || '无描述' }}</p>
 </div>
 </CardContent>
 </Card>
 <Card>
 <CardHeader>
 <CardTitle>时间线</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div>
 <label class="text-sm text-muted-foreground">创建时间</label>
 <p class="text-sm">{{ formatDate(task.created_at) }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">规划开始</label>
 <p class="text-sm">{{ formatDate(task.plan_started_at) }}</p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">规划完成</label>
 <p class="text-sm">{{ formatDate(task.plan_completed_at) }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">执行开始</label>
 <p class="text-sm">{{ formatDate(task.execute_started_at) }}</p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">执行完成</label>
 <p class="text-sm">{{ formatDate(task.execute_completed_at) }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">重试次数</label>
 <p class="text-sm">{{ task.retry_count }}</p>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 状态转换按钮 -->
 <Card v-if="availableTransitions.length > 0" class="mt-4">
 <CardHeader>
 <CardTitle>状态操作</CardTitle>
 <CardDescription>手动转换任务状态</CardDescription>
 </CardHeader>
 <CardContent>
 <div class="flex gap-2">
 <Button
 v-for="status in availableTransitions":key="status"
 variant="outline":disabled="transitioning"
 @click="handleTransition(status)"
 >
 {{ STATUS_LABELS[status] }}
 </Button>
 </div>
 </CardContent>
 </Card>
 </TabsContent>
 <!-- 执行方案 -->
 <TabsContent value="plan" class="mt-4">
 <Card>
 <CardHeader>
 <CardTitle>AI 生成的执行方案</CardTitle>
 <CardDescription>
 Claude Code 分析代码库后生成的实现方案
 </CardDescription>
 </CardHeader>
 <CardContent>
 <div v-if="task.plan_output" class="prose prose-sm max-w-none">
 <pre class="bg-muted rounded-lg overflow-auto text-sm whitespace-pre-wrap">{{ task.plan_output }}</pre>
 </div>
 <div v-else class="text-center py-8 text-muted-foreground">
 <span class="icon-[lucide--file-text] text-4xl block mb-2"></span>
 <p class="mt-2">尚未生成执行方案</p>
 <p class="text-sm">请先启动规划任务</p>
 </div>
 </CardContent>
 </Card>
 <!-- 人工反馈 -->
 <Card v-if="task.human_feedback" class="mt-4">
 <CardHeader>
 <CardTitle>人工反馈</CardTitle>
 </CardHeader>
 <CardContent>
 <p class="text-sm">{{ task.human_feedback }}</p>
 </CardContent>
 </Card>
 </TabsContent>
 <!-- 运行日志 -->
 <TabsContent value="logs" class="mt-4">
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>容器日志</CardTitle>
 <CardDescription>
 任务执行过程中的实时日志
 </CardDescription>
 </div>
 <div class="flex items-center gap-2">
 <Badge v-if="isPolling" variant="outline" class="animate-pulse">
 <span class="icon-[lucide--refresh-cw] mr-1 animate-spin"></span>
 实时刷新中
 </Badge>
 <Button
 v-if="!isPolling && isRunning"
 variant="outline"
 size="sm"
 @click="startPolling"
 >
 <span class="icon-[lucide--play] mr-1"></span>
 开始刷新
 </Button>
 <Button
 v-if="isPolling"
 variant="outline"
 size="sm"
 @click="stopPolling"
 >
 <span class="icon-[lucide--pause] mr-1"></span>
 停止刷新
 </Button>
 </div>
 </CardHeader>
 <CardContent>
 <div v-if="logs" class="bg-black text-green-400 font-mono text-xs rounded-lg overflow-auto max-">
 <pre class="whitespace-pre-wrap">{{ logs }}</pre>
 </div>
 <div v-else class="text-center py-8 text-muted-foreground">
 <span class="icon-[lucide--terminal] text-4xl block mb-2"></span>
 <p class="mt-2">暂无日志</p>
 <p class="text-sm">任务执行后将在此显示日志</p>
 </div>
 </CardContent>
 </Card>
 <!-- 容器状态 -->
 <Card v-if="tasksStore.containerStatus?.container" class="mt-4">
 <CardHeader>
 <CardTitle>容器状态</CardTitle>
 </CardHeader>
 <CardContent>
 <div class="flex gap-4">
 <Badge variant="outline">
 ID: {{ tasksStore.containerStatus.container.id.slice(0, 12) }}
 </Badge>
 <Badge>
 {{ tasksStore.containerStatus.container.status }}
 </Badge>
 </div>
 </CardContent>
 </Card>
 </TabsContent>
 <!-- Git 信息 -->
 <TabsContent value="git" class="mt-4">
 <Card>
 <CardHeader>
 <CardTitle>Git 仓库信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div>
 <label class="text-sm text-muted-foreground">仓库 URL</label>
 <p class="font-mono text-sm">{{ task.git_repo_url || project?.repo_url || '-' }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">基础分支</label>
 <p class="font-mono text-sm">{{ task.git_branch || project?.default_branch || 'main' }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">功能分支</label>
 <p class="font-mono text-sm">{{ task.branch_name || '-' }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">最新提交</label>
 <p class="font-mono text-sm">{{ task.commit_sha || '-' }}</p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">Pull Request</label>
 <p v-if="task.pr_url">
 <a:href="task.pr_url" target="_blank" class="text-primary hover:underline flex items-center gap-1">
 <span class="icon-[lucide--external-link]"></span>
 {{ task.pr_url }}
 </a>
 </p>
 <p v-else class="text-sm">-</p>
 </div>
 </CardContent>
 </Card>
 </TabsContent>
 </Tabs>
 </template>
 <!-- 任务不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="任务不存在"
 description="未找到该任务，可能已被删除"
 action-label="返回列表"
 @action="router.push('/tasks')"
 />
 <!-- 停止确认对话框 -->
 <ConfirmDialog
 v-model:open="stopDialogOpen"
 title="停止任务"
 description="确定要停止此任务吗？正在执行的容器将被终止。"
 confirm-text="停止"
 variant="destructive":loading="stopping"
 @confirm="handleStop"
 />
 <!-- 删除确认对话框 -->
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