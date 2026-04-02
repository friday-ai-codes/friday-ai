<script setup lang="ts">
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { useErrorHandler } from '~/composables/useErrorHandler'
import EditRepositoryModal from '~/components/repository/EditRepositoryModal.vue'
import IndexHistoryList from '~/components/repository/IndexHistoryList.vue'
import IndexStatsPanel from '~/components/repository/IndexStatsPanel.vue'
import RepositoryIndexCard from '~/components/repository/RepositoryIndexCard.vue'
import WebhookConfigPanel from '~/components/repository/WebhookConfigPanel.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { MarkdownPreview } from '~/components/ui/markdown-editor'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute('/repositories/[id]/')
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { handleError } = useErrorHandler
const { success } = useToast
const { copy } = useClipboard
const repositoryId = computed( => route.params.id)
useHead({
 title: computed( => repositoriesStore.currentRepository?.name
 ? `${repositoriesStore.currentRepository.name} - Friday AI`: '仓库详情 - Friday AI'),
})
// 加载仓库
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 repositoriesStore.fetchRepository(repositoryId.value),
 repositoriesStore.fetchCredential(repositoryId.value),
 ])
 }
 catch (e: unknown) {
 handleError(e, '加载仓库详情')
 }
 finally {
 loading.value = false
 }
})
// 删除仓库
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 deleting.value = true
 try {
 await repositoriesStore.deleteRepository(repositoryId.value)
 success('删除成功', '仓库已删除')
 router.push('/repositories')
 }
 catch (e: unknown) {
 handleError(e, '删除仓库')
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
const repository = computed( => repositoriesStore.currentRepository)
const credential = computed( => repositoriesStore.currentCredential)
// 编辑仓库
const editDialogOpen = ref(false)
async function handleEditSuccess {
 editDialogOpen.value = false
 await repositoriesStore.fetchRepository(repositoryId.value)
}
// 平台图标映射
const platformIcons: Record<string, string> = {
 github: 'icon-[lucide--github]',
 gitlab: 'icon-[simple-icons--gitlab]',
 gitea: 'icon-[simple-icons--gitea]',
 bitbucket: 'icon-[simple-icons--bitbucket]',
}
function copyUrl {
 if (repository.value?.git_url) {
 copy(repository.value.git_url)
 success('已复制仓库 URL')
 }
}
</script>
<template>
 <div class="space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/repositories" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回仓库列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 仓库详情 -->
 <template v-else-if="repository">
 <!-- ==================== 头部区域 ==================== -->
 <div class="relative">
 <div class="absolute -inset-2 bg-gradient-to-r from-violet-500/8 via-purple-500/5 to-cyan-500/8 rounded-3xl blur-2xl" />
 <div class="relative bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl overflow-hidden">
 <!-- 顶部渐变装饰线 -->
 <div class=" bg-gradient-to-r from-violet-500 via-purple-500 to-cyan-500" />
 <div class=" space-y-5">
 <!-- 第一行：标题 + 操作按钮 -->
 <div class="flex items-start justify-between gap-4">
 <div class="flex items-center gap-4 min-w-0">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/15 to-purple-500/10 shrink-0">
 <span class="icon-[lucide--git-branch] text-2xl text-violet-500" />
 </div>
 <div class="min-w-0">
 <div class="flex items-center gap-3 flex-wrap">
 <h1 class="text-2xl font-bold truncate">
 {{ repository.name }}
 </h1>
 <Badge variant="outline" class="shrink-0">
 <span:class="platformIcons[repository.git_platform]" class="mr-1" />
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 <Badge variant="secondary" class="shrink-0 font-mono text-xs">
 <span class="icon-[lucide--git-branch] mr-1 text-[10px]" />
 {{ repository.default_branch }}
 </Badge>
 </div>
 <!-- Git URL -->
 <div class="flex items-center gap-2 mt-1.5">
 <p class="text-sm text-muted-foreground font-mono truncate">
 {{ repository.git_url }}
 </p>
 <button
 class=" rounded hover:bg-muted/60 transition-colors shrink-0"
 title="复制 URL"
 @click="copyUrl"
 >
 <span class="icon-[lucide--copy] text-xs text-muted-foreground" />
 </button>
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2 shrink-0">
 <Button variant="outline" size="sm" class="group" @click="editDialogOpen = true">
 <span class="icon-[lucide--pencil] mr-1.5 group-hover:scale-110 transition-transform" />
 编辑
 </Button>
 <Button variant="outline" size="sm" class="group hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1.5 group-hover:scale-110 transition-transform" />
 删除
 </Button>
 </div>
 </div>
 <!-- 描述 -->
 <div v-if="repository.description" class="text-sm text-muted-foreground pl-[68px]">
 <MarkdownPreview:content="repository.description" />
 </div>
 <!-- 快速状态指示器 -->
 <div class="flex items-center gap-3 pl-[68px] flex-wrap">
 <!-- 凭证状态 -->
 <div
 class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors":class="credential
 ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20': 'bg-muted/60 text-muted-foreground border border-border/50'"
 >
 <span:class="credential ? 'icon-[lucide--shield-check]': 'icon-[lucide--shield-off]'" />
 {{ credential ? '凭证已配置': '未配置凭证' }}
 </div>
 <!-- 关联项目数 -->
 <div class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/50">
 <span class="icon-[lucide--folder]" />
 {{ repository.projects?.length || 0 }} 个关联项目
 </div>
 <!-- 代理 URL -->
 <div v-if="repository.proxy_url" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-600 border border-amber-500/20">
 <span class="icon-[lucide--globe]" />
 已配置代理
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- ==================== Tab 内容区域 ==================== -->
 <Tabs default-value="overview" class="space-y-6">
 <TabsList class="bg-muted/50 border border-border/50">
 <TabsTrigger value="overview" class="gap-1.5">
 <span class="icon-[lucide--layout-dashboard] text-sm" />
 概览
 </TabsTrigger>
 <TabsTrigger value="indexing" class="gap-1.5">
 <span class="icon-[lucide--database] text-sm" />
 代码索引
 </TabsTrigger>
 <TabsTrigger value="automation" class="gap-1.5">
 <span class="icon-[lucide--webhook] text-sm" />
 自动化
 </TabsTrigger>
 </TabsList>
 <!-- ========== 概览 Tab ========== -->
 <TabsContent value="overview" class="space-y-6 mt-0">
 <div class="grid gap-6 lg:grid-cols-3">
 <!-- 左侧：基本信息 -->
 <div class="lg:col-span-2 space-y-6">
 <!-- 仓库信息卡片 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 via-purple-500/5 to-violet-500/10 rounded-3xl blur-xl opacity-60" />
 <div class="relative bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl">
 <div class="px-6 py-4 border-b border-border/50 bg-gradient-to-r from-violet-500/5 to-purple-500/5">
 <h3 class="font-semibold flex items-center gap-2">
 <span class="icon-[lucide--info] text-violet-500" />
 仓库信息
 </h3>
 </div>
 <div class="">
 <div class="grid gap-6 sm:grid-cols-2">
 <div>
 <label class="text-xs text-muted-foreground uppercase tracking-wider">Git 平台</label>
 <p class="text-sm mt-1 font-medium">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground uppercase tracking-wider">默认分支</label>
 <p class="text-sm mt-1 font-mono">
 {{ repository.default_branch }}
 </p>
 </div>
 <div v-if="repository.proxy_url">
 <label class="text-xs text-muted-foreground uppercase tracking-wider">代理 URL</label>
 <p class="text-sm mt-1 font-mono break-all">
 {{ repository.proxy_url }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground uppercase tracking-wider">创建时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(repository.created_at) }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground uppercase tracking-wider">最近更新</label>
 <p class="text-sm mt-1">
 {{ formatDate(repository.updated_at) }}
 </p>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 关联项目 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-primary/10 via-primary/5 to-primary/10 rounded-3xl blur-xl opacity-60" />
 <div class="relative bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl">
 <div class="px-6 py-4 border-b border-border/50 bg-gradient-to-r from-primary/5 to-primary/10">
 <h3 class="font-semibold flex items-center gap-2">
 <span class="icon-[lucide--folder] text-primary" />
 关联项目
 </h3>
 </div>
 <div class="">
 <div v-if="!repository.projects || repository.projects.length === 0" class="text-center py-8">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--folder] text-2xl text-muted-foreground" />
 </div>
 <p class="text-sm text-muted-foreground">
 暂无关联项目
 </p>
 </div>
 <div v-else class="space-y-2">
 <RouterLink
 v-for="project in repository.projects":key="project.id":to="`/projects/${project.id}`"
 class="flex items-center justify-between .5 rounded-xl border border-border/50 bg-muted/20 hover:bg-muted/40 hover:border-primary/30 transition-all group"
 >
 <div class="flex items-center gap-3">
 <div class="w-8 rounded-lg bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-sm text-primary" />
 </div>
 <span class="font-medium text-sm group-hover:text-primary transition-colors">{{ project.name }}</span>
 </div>
 <span class="icon-[lucide--chevron-right] text-muted-foreground group-hover:translate-x-1 transition-transform" />
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 右侧：凭证状态 -->
 <div>
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-amber-500/10 via-orange-500/5 to-amber-500/10 rounded-3xl blur-xl opacity-60" />
 <div class="relative bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl">
 <div class="px-6 py-4 border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5 flex items-center justify-between">
 <h3 class="font-semibold flex items-center gap-2">
 <span class="icon-[lucide--key] text-amber-500" />
 凭证配置
 </h3>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="credential" class="space-y-5">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-xl text-emerald-500" />
 </div>
 <div>
 <p class="font-medium text-sm">
 凭证已配置
 </p>
 <p class="text-xs text-muted-foreground mt-0.5">
 {{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </p>
 </div>
 </div>
 <div class="space-y-3 pt-2 border-t border-border/50">
 <div>
 <label class="text-xs text-muted-foreground">Git 用户名</label>
 <p class="text-sm mt-0.5 font-medium">
 {{ credential.git_user_name || '-' }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">Git 邮箱</label>
 <p class="text-sm mt-0.5">
 {{ credential.git_user_email || '-' }}
 </p>
 </div>
 </div>
 </div>
 <div v-else class="text-center py-8">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--lock] text-2xl text-muted-foreground" />
 </div>
 <p class="text-sm text-muted-foreground mb-4">
 尚未配置凭证
 </p>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button size="sm">
 <span class="icon-[lucide--key] mr-1.5" />
 配置凭证
 </Button>
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
 </TabsContent>
 <!-- ========== 代码索引 Tab ========== -->
 <TabsContent value="indexing" class="space-y-6 mt-0">
 <div class="grid gap-6 lg:grid-cols-2">
 <!-- 索引状态与操作 -->
 <RepositoryIndexCard:repository-id="repository.id" />
 <!-- 索引统计 -->
 <IndexStatsPanel:repository-id="repository.id" />
 </div>
 <!-- 索引历史 - 全宽 -->
 <IndexHistoryList:repository-id="repository.id" />
 </TabsContent>
 <!-- ========== 自动化 Tab ========== -->
 <TabsContent value="automation" class="mt-0">
 <div class="max-w-3xl">
 <WebhookConfigPanel:repository="repository" @updated="repositoriesStore.fetchRepository(repositoryId)" />
 </div>
 </TabsContent>
 </Tabs>
 </template>
 <!-- 仓库不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="仓库不存在"
 description="未找到该仓库，可能已被删除"
 action-label="返回列表"
 gradient="from-violet-500/20 to-purple-500/20"
 @action="router.push('/repositories')"
 />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除仓库"
 description="确定要删除此仓库吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 <!-- 编辑对话框 -->
 <EditRepositoryModal
 v-if="repository"
 v-model="editDialogOpen":repository="repository"
 @confirm="handleEditSuccess"
 @cancel="editDialogOpen = false"
 @closed="editDialogOpen = false"
 />
 </div>
</template>
