<script setup lang="ts">
import type { IndexStatusResponse } from '~/api/repositories'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
import { useErrorHandler } from '~/composables/useErrorHandler'
import EditRepositoryModal from '~/components/repository/EditRepositoryModal.vue'
import IndexHistoryList from '~/components/repository/IndexHistoryList.vue'
import IndexStatsPanel from '~/components/repository/IndexStatsPanel.vue'
import AISummarySection from '~/components/repository/AISummarySection.vue'
import RepositoryIndexCard from '~/components/repository/RepositoryIndexCard.vue'
import WebhookConfigPanel from '~/components/repository/WebhookConfigPanel.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { MarkdownPreview } from '~/components/ui/markdown-editor'
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
const indexStatus = ref<IndexStatusResponse | null>(null)
async function loadIndexStatus {
 try {
 indexStatus.value = await repositoriesApi.getIndexStatus(repositoryId.value)
 }
 catch {
 // intentionally ignored
 }
}
onMounted(async => {
 try {
 await Promise.all([
 repositoriesStore.fetchRepository(repositoryId.value),
 repositoriesStore.fetchCredential(repositoryId.value),
 loadIndexStatus,
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
// 描述折叠
const descExpanded = ref(false)
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
 <div class="card overflow-hidden">
 <!-- 顶部装饰线 -->
 <div class=".5 bg-gradient-to-r from-primary via-primary/70 to-primary/40" />
 <div class=" space-y-4">
 <!-- 第一行：标题 + 操作按钮 -->
 <div class="flex items-start justify-between gap-4">
 <div class="flex items-center gap-3 min-w-0">
 <div class=" rounded-lg bg-primary/10 shrink-0">
 <span class="icon-[lucide--git-branch] text-xl text-primary" />
 </div>
 <div class="min-w-0">
 <div class="flex items-center gap-2 flex-wrap">
 <h1 class="text-xl font-bold text-foreground truncate">
 {{ repository.name }}
 </h1>
 <Badge variant="outline" class="shrink-0 text-xs">
 <span:class="platformIcons[repository.git_platform]" class="mr-1" />
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 <Badge variant="secondary" class="shrink-0 font-mono text-xs">
 <span class="icon-[lucide--git-branch] mr-1 text-[10px]" />
 {{ repository.default_branch }}
 </Badge>
 </div>
 <!-- Git URL -->
 <div class="flex items-center gap-1.5 mt-1">
 <p class="text-xs text-muted-foreground font-mono truncate">
 {{ repository.git_url }}
 </p>
 <button
 class=".5 rounded hover:bg-muted/60 transition-colors shrink-0"
 title="复制 URL"
 @click="copyUrl"
 >
 <span class="icon-[lucide--copy] text-xs text-muted-foreground" />
 </button>
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2 shrink-0">
 <Button variant="outline" size="sm" class=" text-xs" @click="editDialogOpen = true">
 <span class="icon-[lucide--pencil] mr-1.5" />
 编辑
 </Button>
 <Button variant="outline" size="sm" class=" text-xs hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1.5" />
 删除
 </Button>
 </div>
 </div>
 <!-- 快速状态指示器 -->
 <div class="flex items-center gap-2 pl-[52px] flex-wrap">
 <div
 class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium":class="{
 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20': indexStatus?.index_status === IndexStatus.INDEXED,
 'bg-blue-500/10 text-blue-600 border border-blue-500/20': indexStatus?.index_status === IndexStatus.INDEXING,
 'bg-red-500/10 text-red-600 border border-red-500/20': indexStatus?.index_status === IndexStatus.FAILED,
 'bg-amber-500/10 text-amber-600 border border-amber-500/20': !indexStatus || indexStatus.index_status === IndexStatus.NOT_INDEXED,
 }"
 >
 <span:class="{
 'icon-[lucide--check-circle]': indexStatus?.index_status === IndexStatus.INDEXED,
 'icon-[lucide--loader-circle] animate-spin': indexStatus?.index_status === IndexStatus.INDEXING,
 'icon-[lucide--x-circle]': indexStatus?.index_status === IndexStatus.FAILED,
 'icon-[lucide--database]': !indexStatus || indexStatus.index_status === IndexStatus.NOT_INDEXED,
 }"
 />
 {{
 indexStatus?.index_status === IndexStatus.INDEXED ? '索引就绪': indexStatus?.index_status === IndexStatus.INDEXING ? '索引构建中': indexStatus?.index_status === IndexStatus.FAILED ? '索引失败': '未建索引'
 }}
 </div>
 <div
 class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium":class="credential
 ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20': 'bg-muted/60 text-muted-foreground border border-border/50'"
 >
 <span:class="credential ? 'icon-[lucide--shield-check]': 'icon-[lucide--shield-off]'" />
 {{ credential ? '凭证已配置': '未配置凭证' }}
 </div>
 <div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/50">
 <span class="icon-[lucide--folder]" />
 {{ repository.projects?.length || 0 }} 个关联项目
 </div>
 <div v-if="repository.proxy_url" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-600 border border-amber-500/20">
 <span class="icon-[lucide--globe]" />
 已配置代理
 </div>
 </div>
 <!-- 描述（可折叠，默认收起） -->
 <div v-if="repository.description" class="pl-[52px]">
 <button
 class="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
 @click="descExpanded = !descExpanded"
 >
 <span
 class="icon-[lucide--chevron-right] transition-transform duration-200":class="{ 'rotate-90': descExpanded }"
 />
 <span class="icon-[lucide--file-text]" />
 AI 描述
 </button>
 <div
 v-if="descExpanded"
 class="mt-2 text-sm text-muted-foreground max-h-[200px] overflow-y-auto rounded-lg bg-muted/30 border border-border/40 "
 >
 <MarkdownPreview:content="repository.description" />
 </div>
 </div>
 </div>
 </div>
 <!-- ==================== AI 智能描述 ==================== -->
 <AISummarySection:repository-id="repository.id" />
 <!-- ==================== 代码索引（第一优先级） ==================== -->
 <div class="space-y-4">
 <div class="grid gap-4 lg:grid-cols-2">
 <RepositoryIndexCard:repository-id="repository.id" />
 <IndexStatsPanel:repository-id="repository.id" />
 </div>
 <IndexHistoryList:repository-id="repository.id" />
 </div>
 <!-- ==================== 仓库信息 & 凭证 ==================== -->
 <div class="grid gap-4 lg:grid-cols-3">
 <div class="lg:col-span-2 space-y-4">
 <!-- 仓库信息卡片 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--info] text-primary" />
 <h3 class="text-sm font-semibold">仓库信息</h3>
 </div>
 <div class="">
 <div class="grid gap-5 sm:grid-cols-2">
 <div>
 <label class="text-xs text-muted-foreground">Git 平台</label>
 <p class="text-sm mt-1 font-medium text-foreground">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">默认分支</label>
 <p class="text-sm mt-1 font-mono text-foreground">
 {{ repository.default_branch }}
 </p>
 </div>
 <div v-if="repository.proxy_url">
 <label class="text-xs text-muted-foreground">代理 URL</label>
 <p class="text-sm mt-1 font-mono break-all text-foreground">
 {{ repository.proxy_url }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1 text-foreground">
 {{ formatDate(repository.created_at) }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">最近更新</label>
 <p class="text-sm mt-1 text-foreground">
 {{ formatDate(repository.updated_at) }}
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- 关联项目 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--folder] text-primary" />
 <h3 class="text-sm font-semibold">关联项目</h3>
 <span class="text-xs text-muted-foreground">({{ repository.projects?.length || 0 }})</span>
 </div>
 <div class="">
 <div v-if="!repository.projects || repository.projects.length === 0" class="text-center py-6">
 <span class="icon-[lucide--folder] text-2xl text-muted-foreground/40 block mb-2" />
 <p class="text-sm text-muted-foreground">暂无关联项目</p>
 </div>
 <div v-else class="space-y-1.5">
 <RouterLink
 v-for="project in repository.projects":key="project.id":to="`/projects/${project.id}`"
 class="flex items-center justify-between .5 rounded-lg hover:bg-muted/40 transition-colors group"
 >
 <div class="flex items-center gap-2.5">
 <div class="w-7 rounded-lg bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-xs text-primary" />
 </div>
 <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ project.name }}</span>
 </div>
 <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
 <!-- 右侧：凭证 -->
 <div class="card h-fit">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--key] text-primary" />
 <h3 class="text-sm font-semibold">凭证配置</h3>
 </div>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="credential" class="space-y-4">
 <div class="flex items-center gap-2.5">
 <div class=".5 rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-lg text-emerald-500" />
 </div>
 <div>
 <p class="text-sm font-medium text-foreground">凭证已配置</p>
 <p class="text-xs text-muted-foreground">
 {{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </p>
 </div>
 </div>
 <div class="space-y-3 pt-3 border-t border-border/50">
 <div>
 <label class="text-xs text-muted-foreground">Git 用户名</label>
 <p class="text-sm mt-0.5 font-medium text-foreground">
 {{ credential.git_user_name || '-' }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">Git 邮箱</label>
 <p class="text-sm mt-0.5 text-foreground">
 {{ credential.git_user_email || '-' }}
 </p>
 </div>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <span class="icon-[lucide--lock] text-2xl text-muted-foreground/40 block mb-2" />
 <p class="text-sm text-muted-foreground mb-3">尚未配置凭证</p>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button size="sm" class=" text-xs">
 <span class="icon-[lucide--key] mr-1.5" />
 配置凭证
 </Button>
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
 <!-- ==================== 自动化 ==================== -->
 <div class="max-w-3xl">
 <WebhookConfigPanel:repository="repository" @updated="repositoriesStore.fetchRepository(repositoryId)" />
 </div>
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
