<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Separator } from '~/components/ui/separator'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
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
 projectsStore.fetchCredential(projectId.value),
 tasksStore.fetchTasks({ project_id: projectId.value }),
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
const credential = computed( => projectsStore.currentCredential)
const projectTasks = computed( => tasksStore.tasks)
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
 <p class="text-muted-foreground flex items-center gap-2 mt-1">
 <Badge variant="outline">
 {{ PLATFORM_LABELS[project.git_platform] }}
 </Badge>
 <span>{{ project.default_branch }}</span>
 </p>
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
 <div>
 <label class="text-sm text-muted-foreground">仓库 URL</label>
 <p class="font-mono text-sm mt-1 break-all">
 {{ project.repo_url }}
 </p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">developer-notes.md 路径</label>
 <p class="font-mono text-sm mt-1">
 {{ project.claude_md_path }}
 </p>
 </div>
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
 <!-- 凭证状态 -->
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>凭证配置</CardTitle>
 <CardDescription>Git 仓库访问凭证</CardDescription>
 </div>
 <RouterLink:to="`/projects/${project.id}/credential`">
 <Button variant="outline" size="sm">
 <span class="icon-[lucide--key] mr-2" />
 管理凭证
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent>
 <div v-if="credential" class="space-y-4">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--check-circle] text-2xl text-green-600" />
 <div>
 <p class="font-medium">
 凭证已配置
 </p>
 <p class="text-sm text-muted-foreground">
 类型：{{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </p>
 </div>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">Git 用户</label>
 <p class="text-sm mt-1">
 {{ credential.git_user_name }} &lt;{{ credential.git_user_email }}&gt;
 </p>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <span class="icon-[lucide--lock] text-4xl text-muted-foreground" />
 <p class="mt-2 text-muted-foreground">
 尚未配置凭证
 </p>
 <RouterLink:to="`/projects/${project.id}/credential`">
 <Button class="mt-4" size="sm">
 配置凭证
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
</template>
