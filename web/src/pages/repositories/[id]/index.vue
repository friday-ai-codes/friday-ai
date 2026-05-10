<script setup lang="ts">
import type { BranchIndexRow, IndexStatusResponse } from '~/api/repositories'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
import ConfirmDialog from '~/components/common/ConfirmDialog.vue'
import AnchorNavLayout, { type NavSection } from '~/components/layout/AnchorNavLayout.vue'
import AISummarySection from '~/components/repository/AISummarySection.vue'
import BranchCombobox from '~/components/repository/BranchCombobox.vue'
import BranchIndexHealthSection from '~/components/repository/BranchIndexHealthSection.vue'
import EditRepositoryModal from '~/components/repository/EditRepositoryModal.vue'
import IndexHistoryList from '~/components/repository/IndexHistoryList.vue'
import IndexStatsPanel from '~/components/repository/IndexStatsPanel.vue'
import RepositoryIndexCard from '~/components/repository/RepositoryIndexCard.vue'
import WebhookConfigPanel from '~/components/repository/WebhookConfigPanel.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { MarkdownPreview } from '~/components/ui/markdown-editor'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
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
const branchIndexRows = ref<BranchIndexRow>
const selectedBranch = ref<string | null>(null)
const rebuildDialogOpen = ref(false)
const rebuildingBranch = ref(false)
let branchIndexPollTimer: ReturnType<typeof setInterval> | null = null
async function loadIndexStatus {
 try {
 indexStatus.value = await repositoriesApi.getIndexStatus(repositoryId.value)
 }
 catch {
 // intentionally ignored
 }
}
function branchStorageKey(repoId: string) {
 return `friday:repo-branch:${repoId}`
}
async function loadBranchIndexes {
 try {
 branchIndexRows.value = await repositoriesApi.getBranchIndexes(repositoryId.value)
 const names = branchIndexRows.value.map(r => r.branch_name)
 const repo = repositoriesStore.currentRepository
 const fromSession = sessionStorage.getItem(branchStorageKey(repositoryId.value))
 if (fromSession && names.includes(fromSession)) {
 selectedBranch.value = fromSession
 return
 }
 if (selectedBranch.value && names.includes(selectedBranch.value))
 return
 const baseRow = branchIndexRows.value.find(r => r.is_base_branch)
 const baseName = repo?.base_branch ?? null
 const defName = repo?.default_branch ?? null
 selectedBranch.value
 = baseRow?.branch_name
 ?? (baseName && names.includes(baseName) ? baseName: null)
 ?? (defName && names.includes(defName) ? defName: null)
 ?? names[0]
 ?? null
 }
 catch {
 branchIndexRows.value =
 }
}
function startBranchIndexPolling {
 if (branchIndexPollTimer)
 return
 branchIndexPollTimer = setInterval(async => {
 await loadIndexStatus
 await loadBranchIndexes
 if (indexStatus.value?.index_status !== IndexStatus.INDEXING) {
 if (branchIndexPollTimer) {
 clearInterval(branchIndexPollTimer)
 branchIndexPollTimer = null
 }
 }
 }, 3000)
}
watch(selectedBranch, (name) => {
 const id = repositoryId.value
 if (name && id)
 sessionStorage.setItem(branchStorageKey(id), name)
})
onMounted(async => {
 try {
 await Promise.all([
 repositoriesStore.fetchRepository(repositoryId.value),
 repositoriesStore.fetchCredential(repositoryId.value),
 loadIndexStatus,
 ])
 await loadBranchIndexes
 if (indexStatus.value?.index_status === IndexStatus.INDEXING)
 startBranchIndexPolling
 }
 catch (e: unknown) {
 handleError(e, '加载仓库详情')
 }
 finally {
 loading.value = false
 }
})
onUnmounted( => {
 if (branchIndexPollTimer) {
 clearInterval(branchIndexPollTimer)
 branchIndexPollTimer = null
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
const branchNames = computed( => branchIndexRows.value.map(r => r.branch_name))
const recommendedBaseBranch = computed( => {
 const base = branchIndexRows.value.find(r => r.is_base_branch)
 if (base)
 return base.branch_name
 const b = repository.value?.base_branch
 if (b && branchNames.value.includes(b))
 return b
 return repository.value?.default_branch ?? null
})
const selectedBranchRow = computed(
 => branchIndexRows.value.find(r => r.branch_name === selectedBranch.value) ?? null,
)
const indexGlobalBusy = computed(
 => indexStatus.value?.index_status === IndexStatus.INDEXING,
)
const rebuildConfirmDescription = computed( => {
 const b = selectedBranch.value ?? '—'
 return `将为分支 ${b} 触发后台重建；全局索引进行中时请勿重复提交。`
})
async function confirmRebuildBranchIndex {
 if (!repository.value || !selectedBranch.value)
 return
 rebuildingBranch.value = true
 try {
 await repositoriesApi.triggerIndex(repository.value.id, { branch: selectedBranch.value })
 success('已提交重建任务', selectedBranch.value)
 rebuildDialogOpen.value = false
 await loadIndexStatus
 await loadBranchIndexes
 startBranchIndexPolling
 }
 catch (e: unknown) {
 handleError(e, '重建分支索引')
 }
 finally {
 rebuildingBranch.value = false
 }
}
// 描述折叠
const descExpanded = ref(false)
const sections = ref<NavSection>([
 { id: 'basic-info', label: '基本信息', icon: 'icon-[lucide--info]' },
 { id: 'branch-index', label: '分支索引', icon: 'icon-[lucide--git-branch]' },
 { id: 'index-stats', label: '索引统计', icon: 'icon-[lucide--bar-chart-3]' },
 { id: 'linked-projects', label: '关联空间', icon: 'icon-[lucide--folder]' },
 { id: 'credential', label: '凭证配置', icon: 'icon-[lucide--key]' },
 { id: 'webhook', label: 'Webhook 自动化', icon: 'icon-[lucide--webhook]' },
 { id: 'danger-zone', label: '危险操作', icon: 'icon-[lucide--alert-triangle]' },
])
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
 <div class=".5" />
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
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class=".5 rounded hover:bg-muted/60 transition-colors shrink-0"
 @click="copyUrl"
 >
 <span class="icon-[lucide--copy] text-xs text-muted-foreground" />
 </button>
 </TooltipTrigger>
 <TooltipContent>复制 URL</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2 shrink-0">
 <Button variant="outline" size="sm" class=" text-xs" @click="editDialogOpen = true">
 <span class="icon-[lucide--pencil] mr-1.5" />
 编辑
 </Button>
 </div>
 </div>
 <!-- 快速状态指示器 -->
 <div class="flex items-center gap-2 pl-[52px] flex-wrap">
 <div
 class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium":class="{ 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20': indexStatus?.index_status === IndexStatus.INDEXED, 'bg-blue-500/10 text-blue-600 border border-blue-500/20': indexStatus?.index_status === IndexStatus.INDEXING, 'bg-red-500/10 text-red-600 border border-red-500/20': indexStatus?.index_status === IndexStatus.FAILED, 'bg-amber-500/10 text-amber-600 border border-amber-500/20': !indexStatus || indexStatus.index_status === IndexStatus.NOT_INDEXED }"
 >
 <span:class="{ 'icon-[lucide--check-circle]': indexStatus?.index_status === IndexStatus.INDEXED, 'icon-[lucide--loader-circle] animate-spin': indexStatus?.index_status === IndexStatus.INDEXING, 'icon-[lucide--x-circle]': indexStatus?.index_status === IndexStatus.FAILED, 'icon-[lucide--database]': !indexStatus || indexStatus.index_status === IndexStatus.NOT_INDEXED }"
 />
 {{
 indexStatus?.index_status === IndexStatus.INDEXED ? '索引就绪': indexStatus?.index_status === IndexStatus.INDEXING ? '索引构建中': indexStatus?.index_status === IndexStatus.FAILED ? '索引失败': '未建索引'
 }}
 </div>
 <div
 class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium":class="credential ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20': 'bg-muted/60 text-muted-foreground border border-border/50'"
 >
 <span:class="credential ? 'icon-[lucide--shield-check]': 'icon-[lucide--shield-off]'" />
 {{ credential ? '凭证已配置': '未配置凭证' }}
 </div>
 <div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/50">
 <span class="icon-[lucide--folder]" />
 {{ repository.projects?.length || 0 }} 个关联空间
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
 <AnchorNavLayout:sections="sections">
 <!-- ==================== 基本信息 ==================== -->
 <section id="basic-info" class="scroll-mt-22 space-y-4">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--info] text-primary" />
 <h3 class="text-sm font-semibold">
 仓库信息
 </h3>
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
 <AISummarySection:repository-id="repository.id" />
 <!-- 关联空间 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--folder] text-primary" />
 <h3 class="text-sm font-semibold">
 关联空间
 </h3>
 <span class="text-xs text-muted-foreground">({{ repository.projects?.length || 0 }})</span>
 </div>
 <div class="">
 <div v-if="!repository.projects || repository.projects.length === 0" class="text-center py-6">
 <span class="icon-[lucide--folder] text-2xl text-muted-foreground/40 block mb-2" />
 <p class="text-sm text-muted-foreground">
 暂无关联空间
 </p>
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
 </section>
 <!-- ==================== 分支索引 ==================== -->
 <section id="branch-index" class="scroll-mt-22">
 <div v-if="branchNames.length > 0" class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-branch] text-primary" />
 <h3 class="text-sm font-semibold">
 分支索引
 </h3>
 <span class="text-xs text-muted-foreground">选择检索分支与健康状态</span>
 </div>
 <div class=" space-y-4">
 <div class="grid gap-4 lg:grid-cols-2 lg:items-start">
 <div class="space-y-2">
 <label class="text-xs text-muted-foreground">当前分支</label>
 <BranchCombobox
 v-model="selectedBranch":branches="branchNames":index-rows="branchIndexRows":recommended-branch="recommendedBaseBranch":disabled="indexGlobalBusy"
 />
 </div>
 <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
 <Button
 v-if="selectedBranchRow?.is_stale":disabled="indexGlobalBusy || rebuildingBranch"
 class="w-full sm:w-auto"
 @click="rebuildDialogOpen = true"
 >
 <span
 v-if="rebuildingBranch"
 class="icon-[lucide--loader-circle] animate-spin mr-2"
 />
 <span v-else class="icon-[lucide--refresh-cw] mr-2" />
 重建索引
 </Button>
 </div>
 </div>
 <BranchIndexHealthSection:row="selectedBranchRow" />
 </div>
 </div>
 </section>
 <!-- ==================== 索引统计 ==================== -->
 <section id="index-stats" class="scroll-mt-22 space-y-4">
 <div class="grid gap-4 lg:grid-cols-2">
 <RepositoryIndexCard:repository-id="repository.id" />
 <IndexStatsPanel:repository-id="repository.id" />
 </div>
 <IndexHistoryList:repository-id="repository.id" />
 </section>
 <!-- ==================== 凭证配置 ==================== -->
 <section id="credential" class="scroll-mt-22">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--key] text-primary" />
 <h3 class="text-sm font-semibold">
 凭证配置
 </h3>
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
 <p class="text-sm font-medium text-foreground">
 凭证已配置
 </p>
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
 <p class="text-sm text-muted-foreground mb-3">
 尚未配置凭证
 </p>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button size="sm" class=" text-xs">
 <span class="icon-[lucide--key] mr-1.5" />
 配置凭证
 </Button>
 </RouterLink>
 </div>
 </div>
 </div>
 </section>
 <!-- ==================== Webhook 自动化 ==================== -->
 <section id="webhook" class="scroll-mt-22">
 <WebhookConfigPanel:repository="repository" @updated="repositoriesStore.fetchRepository(repositoryId)" />
 </section>
 <!-- ==================== 危险操作 ==================== -->
 <section id="danger-zone" class="scroll-mt-22">
 <div class="card border-destructive/30 bg-destructive/5">
 <div class="px-5 py-3.5 border-b border-destructive/20 flex items-center gap-2">
 <span class="icon-[lucide--alert-triangle] text-destructive" />
 <h3 class="text-sm font-semibold text-destructive">危险操作</h3>
 </div>
 <div class=" space-y-4">
 <div class="flex items-start justify-between gap-4">
 <div>
 <p class="text-sm font-medium text-foreground">删除仓库</p>
 <p class="text-xs text-muted-foreground mt-1">删除后无法恢复，相关的凭证配置也将被清除。</p>
 </div>
 <Button variant="destructive" size="sm" class="shrink-0" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1.5" />
 删除仓库
 </Button>
 </div>
 </div>
 </div>
 </section>
 </AnchorNavLayout>
 </template>
 <!-- 仓库不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="仓库不存在"
 description="未找到该仓库，可能已被删除"
 action-label="返回列表"
 gradient="from-primary/20 to-primary/10"
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
 <ConfirmDialog
 v-model:open="rebuildDialogOpen"
 title="确认重建此分支索引？":description="rebuildConfirmDescription"
 confirm-text="确认重建":loading="rebuildingBranch"
 @confirm="confirmRebuildBranchIndex"
 />
 </div>
</template>
