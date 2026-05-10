<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import PageHeader from '~/components/common/PageHeader.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateRepositoryModal from '~/components/repository/CreateRepositoryModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { PLATFORM_LABELS } from '~/types'
useHead({
 title: '仓库管理 - Friday AI',
})
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { handleError } = useErrorHandler
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
 icon-gradient="from-primary/20 to-primary/10"
 icon-color="text-primary"
 title="仓库管理"
 description="管理您的 Git 仓库和凭证配置"
 >
 <template #actions>
 <Button @click="openCreateRepository">
 <span class="icon-[lucide--plus]" />
 新建仓库
 </Button>
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
 gradient="from-primary/20 to-primary/10"
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
 class=".5 rounded-t-[inherit]":class="{ 'bg-emerald-500': repository.index_status === 'indexed', 'bg-blue-500 animate-pulse': repository.index_status === 'indexing', 'bg-red-500': repository.index_status === 'failed', 'bg-border/30': repository.index_status === 'not_indexed' }"
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
 <div class="flex items-center justify-between px-4 py-2.5 border-t border-border/50 bg-muted/20">
 <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
 查看详情
 <span class="icon-[lucide--arrow-right]" />
 </span>
 <div class="flex items-center gap-1">
 <TooltipProvider:delay-duration="300">
 <RouterLink:to="`/repositories/${repository.id}?tab=indexing`" @click.stop>
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon-sm">
 <span class="icon-[lucide--database]" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>代码索引</TooltipContent>
 </Tooltip>
 </RouterLink>
 <RouterLink:to="`/repositories/${repository.id}/credential`" @click.stop>
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon-sm">
 <span class="icon-[lucide--key]" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>凭证管理</TooltipContent>
 </Tooltip>
 </RouterLink>
 </TooltipProvider>
 </div>
 </div>
 </RouterLink>
 </div>
 </PageContainer>
</template>
