<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateProjectModal from '~/components/project/CreateProjectModal.vue'
import { Badge } from '~/components/ui/badge'
import { useErrorHandler } from '~/composables/useErrorHandler'
useHead({
 title: '项目管理 - Friday AI',
})
const router = useRouter
const projectsStore = useProjectsStore
const { handleError } = useErrorHandler
const { success } = useToast
// 加载项目列表
const loading = ref(true)
onMounted(async => {
 try {
 await projectsStore.fetchProjects
 }
 catch (e: unknown) {
 handleError(e, '加载项目列表')
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
 catch (e: unknown) {
 handleError(e, '删除项目')
 }
 finally {
 deleting.value = false
 }
}
</script>
<template>
 <PageContainer>
 <!-- 页面标题 -->
 <PageHeader
 icon="lucide--folder-git-2"
 icon-gradient="from-primary/20 to-primary/10"
 icon-color="text-primary"
 title="项目管理"
 description="管理您的 Git 仓库项目和凭证配置"
 >
 <template #actions>
 <button class="btn btn-primary" @click="openCreateProject">
 <span class="icon-[lucide--plus]" />
 新建项目
 </button>
 </template>
 </PageHeader>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="projectsStore.projects.length === 0"
 icon="lucide--folder-git-2"
 title="暂无项目"
 description="创建您的第一个项目，开始使用 AI 辅助开发"
 action-label="新建项目"
 gradient="from-primary/20 to-primary/20"
 @action="openCreateProject"
 />
 <!-- 项目列表 -->
 <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
 <RouterLink
 v-for="project in projectsStore.projects":key="project.id":to="`/projects/${project.id}`"
 class="card card-interactive group flex flex-col"
 >
 <div class=" flex-1 space-y-3">
 <!-- 标题行 -->
 <div class="flex items-center gap-2.5">
 <div class=".5 rounded-lg bg-primary/10 shrink-0">
 <span class="icon-[lucide--folder-git-2] text-base text-primary" />
 </div>
 <h3 class="text-sm font-semibold text-foreground group-hover:text-primary transition-colors truncate flex-1">
 {{ project.name }}
 </h3>
 </div>
 <!-- 描述 -->
 <p class="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
 {{ project.description || '暂无描述' }}
 </p>
 <!-- 底部信息行 -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
 <span class="icon-[lucide--git-branch] text-primary/60" />
 <span>{{ project.repositories?.length || 0 }} 个仓库</span>
 </div>
 <Badge:variant="project.has_feishu_config ? 'default': 'secondary'"
 class="text-xs"
 >
 <span:class="project.has_feishu_config ? 'icon-[lucide--check]': 'icon-[lucide--x]'" class="mr-1" />
 {{ project.has_feishu_config ? '飞书': '未配置' }}
 </Badge>
 </div>
 </div>
 <!-- 底部操作栏 -->
 <div class="flex items-center gap-2 px-4 py-2.5 border-t border-border/50">
 <button class="btn btn-secondary btn-sm flex-1" @click.prevent>
 <span class="icon-[lucide--arrow-right]" />
 查看详情
 </button>
 <button
 class="btn btn-ghost btn-icon btn-sm hover:!bg-red-50 hover:!text-red-500"
 @click.prevent="confirmDelete(project.id)"
 >
 <span class="icon-[lucide--trash-2]" />
 </button>
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
