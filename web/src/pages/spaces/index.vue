<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateSpaceModal from '~/components/space/CreateSpaceModal.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
useHead({
 title: '空间管理 - Friday AI',
})
const router = useRouter
const spacesStore = useSpacesStore
const { handleError } = useErrorHandler
// 加载空间列表
const loading = ref(true)
onMounted(async => {
 try {
 await spacesStore.fetchSpaces
 }
 catch (e: unknown) {
 handleError(e, '加载空间列表')
 }
 finally {
 loading.value = false
 }
})
// 新建空间弹窗
async function openCreateSpace {
 const { open } = useModal<string>({
 component: markRaw(CreateSpaceModal),
 onConfirm: (spaceId) => {
 // 创建成功后跳转到空间详情
 router.push(`/spaces/${spaceId}`)
 },
 })
 await open
}
</script>
<template>
 <PageContainer>
 <!-- 页面标题 -->
 <PageHeader
 icon="lucide--folder-git-2"
 icon-gradient="from-primary/20 to-primary/10"
 icon-color="text-primary"
 title="空间管理"
 description="管理您的 Git 仓库空间和凭证配置"
 >
 <template #actions>
 <Button @click="openCreateSpace">
 <span class="icon-[lucide--plus]" />
 新建空间
 </Button>
 </template>
 </PageHeader>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="spacesStore.spaces.length === 0"
 icon="lucide--folder-git-2"
 title="暂无空间"
 description="创建您的第一个空间，开始使用 AI 辅助开发"
 action-label="新建空间"
 gradient="from-primary/20 to-primary/20"
 @action="openCreateSpace"
 />
 <!-- 空间列表 -->
 <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
 <RouterLink
 v-for="space in spacesStore.spaces":key="space.id":to="`/spaces/${space.id}`"
 class="card card-interactive group flex flex-col"
 >
 <div class=" flex-1 space-y-3">
 <!-- 标题行 -->
 <div class="flex items-center gap-2.5">
 <div class=".5 rounded-lg bg-primary/10 shrink-0">
 <span class="icon-[lucide--folder-git-2] text-base text-primary" />
 </div>
 <h3 class="text-sm font-semibold text-foreground group-hover:text-primary transition-colors truncate flex-1">
 {{ space.name }}
 </h3>
 </div>
 <!-- 描述 -->
 <p v-if="space.description" class="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
 {{ space.description }}
 </p>
 <!-- 最近工作项 -->
 <div v-if="space.recent_work_items?.length" class="flex flex-col gap-1.5 pt-1">
 <button
 v-for="item in space.recent_work_items":key="item.id"
 class="group/item flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors text-left w-full"
 @click.prevent="router.push(`/logs/triggers/${item.id}`)"
 >
 <span class="w-1 rounded-full bg-muted-foreground/30 group-hover/item:bg-primary group-hover/item:scale-150 transition-all shrink-0" />
 <span class="truncate flex-1 group-hover/item:text-primary transition-colors":title="item.name">{{ item.name }}</span>
 </button>
 </div>
 <!-- 底部信息行 -->
 <div class="flex items-center gap-4 mt-auto pt-2">
 <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
 <span class="icon-[lucide--git-branch] text-primary/60" />
 <span>{{ space.repositories?.length || 0 }} 个仓库</span>
 </div>
 <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
 <span class="icon-[lucide--play-circle] text-primary/60" />
 <span>{{ space.execution_count || 0 }} 次执行</span>
 </div>
 </div>
 </div>
 <!-- 底部操作栏 -->
 <div class="flex items-center px-4 py-2.5 border-t border-border/50 bg-muted/20">
 <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
 查看详情
 <span class="icon-[lucide--arrow-right]" />
 </span>
 </div>
 </RouterLink>
 </div>
 </PageContainer>
</template>
