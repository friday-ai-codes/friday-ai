<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { PLATFORM_LABELS } from '~/types'
useHead({
 title: '仓库管理 - Friday AI',
})
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
</script>
<template>
 <div class="space-y-6">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div>
 <h1 class="text-2xl font-bold">
 仓库管理
 </h1>
 <p class="text-muted-foreground">
 管理您的 Git 仓库和凭证配置
 </p>
 </div>
 <RouterLink to="/repositories/new">
 <Button>
 <span class="icon-[lucide--plus] mr-2" />
 新建仓库
 </Button>
 </RouterLink>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="repositoriesStore.repositories.length === 0"
 icon="lucide--git-branch"
 title="暂无仓库"
 description="创建您的第一个仓库，关联到项目以开始使用"
 action-label="新建仓库"
 @action="$router.push('/repositories/new')"
 />
 <!-- 仓库列表 -->
 <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
 <Card
 v-for="repository in repositoriesStore.repositories":key="repository.id"
 class="hover:shadow-md transition-shadow"
 >
 <CardHeader class="pb-3">
 <div class="flex items-start justify-between">
 <div class="space-y-1">
 <CardTitle class="text-lg">
 {{ repository.name }}
 </CardTitle>
 <CardDescription class="flex items-center gap-2">
 <Badge variant="outline">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 <span class="text-xs">{{ repository.default_branch }}</span>
 </CardDescription>
 </div>
 <Badge:variant="repository.has_credential ? 'default': 'secondary'">
 <span:class="repository.has_credential ? 'icon-[lucide--check]': 'icon-[lucide--x]'" class="mr-1" />
 {{ repository.has_credential ? '已配置凭证': '未配置凭证' }}
 </Badge>
 </div>
 </CardHeader>
 <CardContent class="space-y-4">
 <!-- 仓库 URL -->
 <div class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--link] flex-shrink-0" />
 <span class="truncate":title="repository.git_url">{{ repository.git_url }}</span>
 </div>
 <!-- 操作按钮 -->
 <div class="flex items-center gap-2">
 <RouterLink:to="`/repositories/${repository.id}`" class="flex-1">
 <Button variant="outline" size="sm" class="w-full">
 <span class="icon-[lucide--eye] mr-1" />
 查看详情
 </Button>
 </RouterLink>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button variant="ghost" size="sm" title="凭证管理">
 <span class="icon-[lucide--key]" />
 </Button>
 </RouterLink>
 <Button
 variant="ghost"
 size="sm"
 title="删除仓库"
 @click="confirmDelete(repository.id)"
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
 title="删除仓库"
 description="确定要删除此仓库吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
</template>
