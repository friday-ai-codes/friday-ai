<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '~/components/ui/select'
import { Separator } from '~/components/ui/separator'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
const repositoriesStore = useRepositoriesStore
const tasksStore = useTasksStore
const { success, error: showError } = useToast
const projectId = computed( => route.params.id as string)
useHead({
 title: computed( => projectsStore.currentProject?.name
 ? `${projectsStore.currentProject.name} - Friday AI`: '项目详情 - Friday AI'),
})
// 加载项目和相关任务
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 projectsStore.fetchProject(projectId.value),
 projectsStore.fetchFeishuConfig(projectId.value),
 tasksStore.fetchTasks({ project_id: projectId.value }),
 repositoriesStore.fetchRepositories, // 加载所有仓库供选择
 ])
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取项目详情')
 }
 finally {
 loading.value = false
 }
})
// 删除项目
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 deleting.value = true
 try {
 await projectsStore.deleteProject(projectId.value)
 success('删除成功', '项目已删除')
 router.push('/projects')
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除项目')
 }
 finally {
 deleting.value = false
 deleteDialogOpen.value = false
 }
}
// 格式化日期
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 计算属性
const project = computed( => projectsStore.currentProject)
const feishuConfig = computed( => projectsStore.currentFeishuConfig)
const projectTasks = computed( => tasksStore.tasks)
// 关联仓库
const linkDialogOpen = ref(false)
const selectedRepositoryId = ref('')
const linking = ref(false)
// 可供关联的仓库（排除已关联的）
const availableRepositories = computed( => {
 if (!project.value)
 return
 const linkedIds = project.value.repositories?.map(r => r.id) ??
 return repositoriesStore.repositories.filter(r => !linkedIds.includes(r.id))
})
async function handleLinkRepository {
 if (!selectedRepositoryId.value)
 return
 linking.value = true
 try {
 await projectsStore.addRepository(projectId.value, selectedRepositoryId.value)
 success('关联成功', '已关联仓库')
 linkDialogOpen.value = false
 selectedRepositoryId.value = ''
 }
 catch (e) {
 showError('关联失败', e instanceof Error ? e.message: '无法关联仓库')
 }
 finally {
 linking.value = false
 }
}
// 解除关联
const unlinking = ref(false)
async function handleUnlinkRepository(repositoryId: string) {
 unlinking.value = true
 try {
 await projectsStore.removeRepository(projectId.value, repositoryId)
 success('解除关联成功', '已解除关联仓库')
 }
 catch (e) {
 showError('解除关联失败', e instanceof Error ? e.message: '无法解除关联仓库')
 }
 finally {
 unlinking.value = false
 }
}
</script>
<template>
 <div class="space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/projects" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回项目列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 项目详情 -->
 <template v-else-if="project">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div>
 <h1 class="text-2xl font-bold">
 {{ project.name }}
 </h1>
 </div>
 <div class="flex items-center gap-2">
 <RouterLink:to="`/projects/${project.id}/edit`">
 <Button variant="outline">
 <span class="icon-[lucide--pencil] mr-2" />
 编辑
 </Button>
 </RouterLink>
 <Button variant="destructive" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 </div>
 <div class="grid gap-6 md:grid-cols-2">
 <!-- 基本信息 -->
 <Card>
 <CardHeader>
 <CardTitle>基本信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">飞书项目 Key</label>
 <p class="font-mono text-sm mt-1">
 {{ project.feishu_project_key || '未配置' }}
 </p>
 </div>
 <Separator />
 <div class="flex gap-8">
 <div>
 <label class="text-sm text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(project.created_at) }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">更新时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(project.updated_at) }}
 </p>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- 关联仓库 -->
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>关联仓库</CardTitle>
 <CardDescription>关联的 Git 仓库</CardDescription>
 </div>
 <Button variant="outline" size="sm" @click="linkDialogOpen = true">
 <span class="icon-[lucide--link] mr-2" />
 关联仓库
 </Button>
 </CardHeader>
 <CardContent>
 <div v-if="project.repositories?.length === 0" class="text-center py-6 text-muted-foreground">
 暂无关联仓库
 </div>
 <div v-else class="space-y-4">
 <div
 v-for="repo in project.repositories":key="repo.id"
 class="flex items-center justify-between border rounded-lg"
 >
 <div>
 <div class="flex items-center gap-2">
 <span class="font-medium">{{ repo.name }}</span>
 <Badge variant="outline">
 {{ PLATFORM_LABELS[repo.git_platform] }}
 </Badge>
 </div>
 <div class="text-sm text-muted-foreground mt-1">
 {{ repo.git_url }}
 </div>
 </div>
 <div class="flex items-center gap-2">
 <RouterLink:to="`/repositories/${repo.id}`">
 <Button variant="ghost" size="sm" title="查看详情">
 <span class="icon-[lucide--eye]" />
 </Button>
 </RouterLink>
 <Button
 variant="ghost"
 size="sm"
 title="解除关联":disabled="unlinking"
 @click="handleUnlinkRepository(repo.id)"
 >
 <span class="icon-[lucide--unlink] text-destructive" />
 </Button>
 </div>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- 飞书配置 -->
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>飞书配置</CardTitle>
 <CardDescription>飞书项目 Webhook 集成</CardDescription>
 </div>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button variant="outline" size="sm">
 <span class="icon-[lucide--settings] mr-2" />
 管理配置
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent>
 <div v-if="feishuConfig" class="space-y-4">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--check-circle] text-2xl text-green-600" />
 <div>
 <p class="font-medium">
 已配置
 </p>
 <p class="text-sm text-muted-foreground">
 插件 ID：{{ feishuConfig.plugin_id }}
 </p>
 </div>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">Webhook Token</label>
 <p class="text-sm mt-1">
 {{ feishuConfig.has_webhook_token ? '已配置': '未配置' }}
 </p>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <span class="icon-[lucide--link] text-4xl text-muted-foreground" />
 <p class="mt-2 text-muted-foreground">
 尚未配置飞书集成
 </p>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button class="mt-4" size="sm">
 配置飞书
 </Button>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 相关任务 -->
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>相关任务</CardTitle>
 <CardDescription>此项目下的所有任务</CardDescription>
 </div>
 <RouterLink:to="`/tasks?project_id=${project.id}`">
 <Button variant="outline" size="sm">
 <span class="icon-[lucide--arrow-right] mr-1" />
 查看全部
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent>
 <div v-if="projectTasks.length === 0" class="text-center py-8 text-muted-foreground">
 <span class="icon-[lucide--inbox] text-4xl block mb-2" />
 暂无任务
 </div>
 <div v-else class="space-y-2">
 <RouterLink
 v-for="task in projectTasks.slice(0, 5)":key="task.id":to="`/tasks/${task.id}`"
 class="flex items-center justify-between rounded-lg hover:bg-muted/50 transition-colors"
 >
 <div class="flex items-center gap-4">
 <span class="font-medium">{{ task.title }}</span>
 <TaskStatusBadge:status="task.status" />
 </div>
 <span class="text-sm text-muted-foreground">
 {{ formatDate(task.created_at) }}
 </span>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目，可能已被删除"
 action-label="返回列表"
 @action="router.push('/projects')"
 />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除项目"
 description="确定要删除此项目吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
 <!-- 关联仓库对话框 -->
 <Dialog v-model:open="linkDialogOpen">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>关联仓库</DialogTitle>
 <DialogDescription>
 选择要关联到此项目的 Git 仓库
 </DialogDescription>
 </DialogHeader>
 <div class="py-4">
 <Select v-model="selectedRepositoryId">
 <SelectTrigger>
 <SelectValue placeholder="选择仓库" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="repo in availableRepositories":key="repo.id":value="repo.id">
 {{ repo.name }} ({{ repo.git_url }})
 </SelectItem>
 </SelectContent>
 </Select>
 <p v-if="availableRepositories.length === 0" class="text-sm text-muted-foreground mt-2">
 没有可关联的仓库，请先<RouterLink to="/repositories/new" class="underline">
 创建仓库
 </RouterLink>
 </p>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="linkDialogOpen = false">
 取消
 </Button>
 <Button:disabled="!selectedRepositoryId || linking" @click="handleLinkRepository">
 {{ linking ? '关联中...': '关联' }}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
