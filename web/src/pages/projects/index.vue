<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
useHead({
 title: '项目管理 - Friday AI',
})
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
// 加载项目列表
const loading = ref(true)
onMounted(async => {
 try {
 await projectsStore.fetchProjects
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取项目列表')
 }
 finally {
 loading.value = false
 }
})
// 删除项目
const deleteDialogOpen = ref(false)
const projectToDelete = ref<string | null>(null)
const deleting = ref(false)
function confirmDelete(projectId: string) {
 projectToDelete.value = projectId
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!projectToDelete.value)
 return
 deleting.value = true
 try {
 await projectsStore.deleteProject(projectToDelete.value)
 success('删除成功', '项目已删除')
 deleteDialogOpen.value = false
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除项目')
 }
 finally {
 deleting.value = false
 }
}
</script>
<template>
 <div class="space-y-6">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div>
 <h1 class="text-2xl font-bold">
 项目管理
 </h1>
 <p class="text-muted-foreground">
 管理您的 Git 仓库项目和凭证配置
 </p>
 </div>
 <RouterLink to="/projects/new">
 <Button>
 <span class="icon-[lucide--plus] mr-2" />
 新建项目
 </Button>
 </RouterLink>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="projectsStore.projects.length === 0"
 icon="lucide--folder-git-2"
 title="暂无项目"
 description="创建您的第一个项目，开始使用 AI 辅助开发"
 action-label="新建项目"
 @action="$router.push('/projects/new')"
 />
 <!-- 项目列表 -->
 <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
 <Card
 v-for="project in projectsStore.projects":key="project.id"
 class="hover:shadow-md transition-shadow"
 >
 <CardHeader class="pb-3">
 <div class="flex items-start justify-between">
 <div class="space-y-1">
 <CardTitle class="text-lg">
 {{ project.name }}
 </CardTitle>
 <CardDescription v-if="project.description" class="line-clamp-2">
 {{ project.description }}
 </CardDescription>
 </div>
 <Badge:variant="project.has_feishu_config ? 'default': 'secondary'">
 <span:class="project.has_feishu_config ? 'icon-[lucide--check]': 'icon-[lucide--x]'" class="mr-1" />
 {{ project.has_feishu_config ? '飞书已配置': '飞书未配置' }}
 </Badge>
 </div>
 </CardHeader>
 <CardContent class="space-y-4">
 <!-- 关联仓库数量 -->
 <div class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--git-branch] flex-shrink-0" />
 <span>{{ project.repositories?.length || 0 }} 个关联仓库</span>
 </div>
 <!-- 操作按钮 -->
 <div class="flex items-center gap-2">
 <RouterLink:to="`/projects/${project.id}`" class="flex-1">
 <Button variant="outline" size="sm" class="w-full">
 <span class="icon-[lucide--eye] mr-1" />
 查看详情
 </Button>
 </RouterLink>
 <Button
 variant="ghost"
 size="sm"
 title="删除项目"
 @click="confirmDelete(project.id)"
 >
 <span class="icon-[lucide--trash-2] text-destructive" />
 </Button>
 </div>
 </CardContent>
 </Card>
 </div>
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
