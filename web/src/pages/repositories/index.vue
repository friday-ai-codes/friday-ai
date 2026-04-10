<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import { useErrorHandler } from '~/composables/useErrorHandler'
import PageHeader from '~/components/common/PageHeader.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateRepositoryModal from '~/components/repository/CreateRepositoryModal.vue'
import { Badge } from '~/components/ui/badge'
import { PLATFORM_LABELS } from '~/types'
useHead({
 title: '仓库管理 - Friday AI',
})
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { handleError } = useErrorHandler
const { success } = useToast
// 加载仓库列表
const loading = ref(true)
onMounted(async => {
 try {
 await repositoriesStore.fetchRepositories
 }
 catch (e: unknown) {
 handleError(e, '加载仓库列表')
 }
 finally {
 loading.value = false
 }
})
// 新建仓库弹窗
async function openCreateRepository {
 const { open } = useModal<string>({
 component: markRaw(CreateRepositoryModal),
 onConfirm: (repositoryId) => {
 router.push(`/repositories/${repositoryId}`)
 },
 })
 await open
}
// 删除仓库
const deleteDialogOpen = ref(false)
const repositoryToDelete = ref<string | null>(null)
const deleting = ref(false)
function confirmDelete(id: string) {
 repositoryToDelete.value = id
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!repositoryToDelete.value)
 return
 deleting.value = true
 try {
 await repositoriesStore.deleteRepository(repositoryToDelete.value)
 success('删除成功', '仓库已删除')
 deleteDialogOpen.value = false
 }
 catch (e: unknown) {
 handleError(e, '删除仓库')
 }
 finally {
 deleting.value = false
 }
}
// 平台图标映射
const platformIcons: Record<string, string> = {
 github: 'lucide--github',
 gitlab: 'simple-icons--gitlab',
 gitee: 'simple-icons--gitee',
}
</script>
<template>
 <PageContainer>
 <!-- 页面标题 -->
 <PageHeader
 icon="lucide--git-branch"
 icon-gradient="from-teal-500/20 to-cyan-500/10"
 icon-color="text-teal-500"
 title="仓库管理"
 description="管理您的 Git 仓库和凭证配置"
 >
 <template #actions>
 <button class="btn btn-primary" @click="openCreateRepository">
 <span class="icon-[lucide--plus]" />
 新建仓库
 </button>
 </template>
 </PageHeader>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="repositoriesStore.repositories.length === 0"
 icon="lucide--git-branch"
 title="暂无仓库"
 description="创建您的第一个仓库，关联到项目以开始使用"
 action-label="新建仓库"
 gradient="from-teal-500/20 to-cyan-500/20"
 @action="openCreateRepository"
 />
 <!-- 仓库列表 -->
 <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
 <RouterLink
 v-for="repository in repositoriesStore.repositories":key="repository.id":to="`/repositories/${repository.id}`"
 class="card card-interactive group flex flex-col"
 >
 <!-- 索引状态顶部指示条 -->
 <div
 class=".5 rounded-t-[inherit]":class="{
 'bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500': repository.index_status === 'indexed',
 'bg-gradient-to-r from-blue-500 via-cyan-400 to-blue-500 animate-pulse': repository.index_status === 'indexing',
 'bg-gradient-to-r from-red-500 to-orange-500': repository.index_status === 'failed',
 'bg-border/30': repository.index_status === 'not_indexed',
 }"
 />
 <div class=" flex-1 space-y-3">
 <!-- 标题行 -->
 <div class="flex items-center gap-2.5">
 <div class=".5 rounded-lg bg-primary/10 shrink-0">
 <span class="text-base text-primary":class="`icon-[${platformIcons[repository.git_platform] || 'lucide--git-branch'}]`" />
 </div>
 <h3 class="text-sm font-semibold text-foreground group-hover:text-primary transition-colors truncate flex-1">
 {{ repository.name }}
 </h3>
 <StatusBadge type="index":status="repository.index_status" size="sm" />
 </div>
 <!-- 平台和分支 -->
 <div class="flex items-center gap-2 flex-wrap">
 <Badge variant="outline" class="text-xs">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 <span class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--git-branch]" />
 {{ repository.default_branch }}
 </span>
 <span v-if="repository.linked_projects_count" class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--folder]" />
 {{ repository.linked_projects_count }} 个项目
 </span>
 </div>
 <!-- 仓库 URL -->
 <p class="text-xs text-muted-foreground font-mono truncate":title="repository.git_url">
 {{ repository.git_url }}
 </p>
 <!-- 索引时间 -->
 <p v-if="repository.last_indexed_at" class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--clock]" />
 索引于 {{ new Date(repository.last_indexed_at).toLocaleString('zh-CN') }}
 </p>
 </div>
 <!-- 底部操作栏 -->
 <div class="flex items-center gap-2 px-4 py-2.5 border-t border-border/50">
 <button class="btn btn-secondary btn-sm flex-1" @click.prevent>
 <span class="icon-[lucide--eye]" />
 查看详情
 </button>
 <RouterLink:to="`/repositories/${repository.id}?tab=indexing`" @click.stop>
 <button class="btn btn-ghost btn-icon btn-sm" title="代码索引">
 <span class="icon-[lucide--database]" />
 </button>
 </RouterLink>
 <RouterLink:to="`/repositories/${repository.id}/credential`" @click.stop>
 <button class="btn btn-ghost btn-icon btn-sm" title="凭证管理">
 <span class="icon-[lucide--key]" />
 </button>
 </RouterLink>
 <button
 class="btn btn-ghost btn-icon btn-sm hover:!bg-red-50 hover:!text-red-500"
 @click.prevent="confirmDelete(repository.id)"
 >
 <span class="icon-[lucide--trash-2]" />
 </button>
 </div>
 </RouterLink>
 </div>
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除仓库"
 description="确定要删除此仓库吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </PageContainer>
</template>
