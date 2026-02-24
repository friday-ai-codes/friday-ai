<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateProjectModal from '~/components/project/CreateProjectModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
useHead({
 title: '项目管理 - Friday AI',
})
const router = useRouter
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
// 新建项目弹窗
async function openCreateProject {
 const { open } = useModal<string>({
 component: markRaw(CreateProjectModal),
 onConfirm: (projectId) => {
 // 创建成功后跳转到项目详情
 router.push(`/projects/${projectId}`)
 },
 })
 await open
}
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
 <PageContainer>
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-git-2] text-2xl text-blue-500" />
 </div>
 <h1 class="text-2xl font-bold">
 项目管理
 </h1>
 </div>
 <p class="text-muted-foreground ml-12">
 管理您的 Git 仓库项目和凭证配置
 </p>
 </div>
 <Button class="group relative overflow-hidden" @click="openCreateProject">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 新建项目
 </Button>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="projectsStore.projects.length === 0"
 icon="lucide--folder-git-2"
 title="暂无项目"
 description="创建您的第一个项目，开始使用 AI 辅助开发"
 action-label="新建项目"
 gradient="from-blue-500/20 to-cyan-500/20"
 @action="openCreateProject"
 />
 <!-- 项目列表 -->
 <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
 <RouterLink
 v-for="project in projectsStore.projects":key="project.id":to="`/projects/${project.id}`"
 class="group relative"
 >
 <!-- 悬浮光晕 -->
 <div class="absolute -inset-0.5 bg-gradient-to-r from-blue-500 to-cyan-500 rounded-2xl opacity-0 group-hover:opacity-20 blur-lg transition-opacity duration-500" />
 <!-- 卡片主体 -->
 <div class="relative h-full rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 group-hover:border-primary/30 group-hover:shadow-lg transition-all duration-300">
 <!-- 头部 -->
 <div class="flex items-start justify-between mb-4">
 <div class=".5 rounded-xl bg-gradient-to-br from-blue-500/10 to-cyan-500/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-git-2] text-2xl text-blue-500" />
 </div>
 <Badge:variant="project.has_feishu_config ? 'default': 'secondary'"
 class="text-xs"
 >
 <span:class="project.has_feishu_config ? 'icon-[lucide--check]': 'icon-[lucide--x]'" class="mr-1" />
 {{ project.has_feishu_config ? '飞书已配置': '飞书未配置' }}
 </Badge>
 </div>
 <!-- 内容 -->
 <div class="space-y-3">
 <h3 class="text-lg font-semibold group-hover:text-primary transition-colors">
 {{ project.name }}
 </h3>
 <p v-if="project.description" class="text-sm text-muted-foreground line-clamp-2">
 {{ project.description }}
 </p>
 <!-- 仓库数量 -->
 <div class="flex items-center gap-2 text-sm text-muted-foreground pt-2">
 <span class="icon-[lucide--git-branch]" />
 <span>{{ project.repositories?.length || 0 }} 个关联仓库</span>
 </div>
 </div>
 <!-- 操作按钮 -->
 <div class="flex items-center gap-2 mt-6 pt-4 border-t border-border/50">
 <Button variant="outline" size="sm" class="flex-1 group/btn" @click.prevent>
 <span class="icon-[lucide--eye] mr-1.5 group-hover/btn:scale-110 transition-transform" />
 查看详情
 </Button>
 <Button
 variant="ghost"
 size="sm"
 class="hover:bg-destructive/10 hover:text-destructive"
 @click.prevent="confirmDelete(project.id)"
 >
 <span class="icon-[lucide--trash-2]" />
 </Button>
 </div>
 </div>
 </RouterLink>
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
 </PageContainer>
</template>
