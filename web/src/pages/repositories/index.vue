<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import CreateRepositoryModal from '~/components/repository/CreateRepositoryModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { PLATFORM_LABELS } from '~/types'
useHead({
 title: '仓库管理 - Friday AI',
})
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { success, error: showError } = useToast
// 加载仓库列表
const loading = ref(true)
onMounted(async => {
 try {
 await repositoriesStore.fetchRepositories
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取仓库列表')
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
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除仓库')
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
 <div class="space-y-8">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--git-branch] text-2xl text-violet-500" />
 </div>
 <h1 class="text-2xl font-bold">
 仓库管理
 </h1>
 </div>
 <p class="text-muted-foreground ml-12">
 管理您的 Git 仓库和凭证配置
 </p>
 </div>
 <Button class="group relative overflow-hidden" @click="openCreateRepository">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 新建仓库
 </Button>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="repositoriesStore.repositories.length === 0"
 icon="lucide--git-branch"
 title="暂无仓库"
 description="创建您的第一个仓库，关联到项目以开始使用"
 action-label="新建仓库"
 gradient="from-violet-500/20 to-purple-500/20"
 @action="$router.push('/repositories/new')"
 />
 <!-- 仓库列表 -->
 <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
 <RouterLink
 v-for="repository in repositoriesStore.repositories":key="repository.id":to="`/repositories/${repository.id}`"
 class="group relative"
 >
 <!-- 悬浮光晕 -->
 <div class="absolute -inset-0.5 bg-gradient-to-r from-violet-500 to-purple-500 rounded-2xl opacity-0 group-hover:opacity-20 blur-lg transition-opacity duration-500" />
 <!-- 卡片主体 -->
 <div class="relative h-full rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 group-hover:border-primary/30 group-hover:shadow-lg transition-all duration-300">
 <!-- 头部 -->
 <div class="flex items-start justify-between mb-4">
 <div class=".5 rounded-xl bg-gradient-to-br from-violet-500/10 to-purple-500/10 flex items-center justify-center">
 <span class="text-2xl text-violet-500":class="`icon-[${platformIcons[repository.git_platform] || 'lucide--git-branch'}]`" />
 </div>
 <Badge:variant="repository.has_credential ? 'default': 'secondary'"
 class="text-xs"
 >
 <span:class="repository.has_credential ? 'icon-[lucide--check]': 'icon-[lucide--x]'" class="mr-1" />
 {{ repository.has_credential ? '已配置凭证': '未配置凭证' }}
 </Badge>
 </div>
 <!-- 内容 -->
 <div class="space-y-3">
 <h3 class="text-lg font-semibold group-hover:text-primary transition-colors">
 {{ repository.name }}
 </h3>
 <!-- 平台和分支 -->
 <div class="flex items-center gap-2">
 <Badge variant="outline" class="text-xs">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 <span class="text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--git-branch]" />
 {{ repository.default_branch }}
 </span>
 </div>
 <!-- 仓库 URL -->
 <div class="flex items-center gap-2 text-sm text-muted-foreground pt-2">
 <span class="icon-[lucide--link] flex-shrink-0" />
 <span class="truncate":title="repository.git_url">{{ repository.git_url }}</span>
 </div>
 </div>
 <!-- 操作按钮 -->
 <div class="flex items-center gap-2 mt-6 pt-4 border-t border-border/50">
 <Button variant="outline" size="sm" class="flex-1 group/btn" @click.prevent>
 <span class="icon-[lucide--eye] mr-1.5 group-hover/btn:scale-110 transition-transform" />
 查看详情
 </Button>
 <RouterLink:to="`/repositories/${repository.id}/credential`" @click.stop>
 <Button variant="ghost" size="sm" title="凭证管理">
 <span class="icon-[lucide--key]" />
 </Button>
 </RouterLink>
 <Button
 variant="ghost"
 size="sm"
 class="hover:bg-destructive/10 hover:text-destructive"
 @click.prevent="confirmDelete(repository.id)"
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
 title="删除仓库"
 description="确定要删除此仓库吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
</template>
