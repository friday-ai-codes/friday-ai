<script setup lang="ts">
import type { BranchIndexRow, IndexStatusResponse } from '~/api/repositories'
import type { NavSection } from '~/components/layout/AnchorNavLayout.vue'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import ConfirmDialog from '~/components/common/ConfirmDialog.vue'
import AnchorNavLayout from '~/components/layout/AnchorNavLayout.vue'
import AISummarySection from '~/components/repository/AISummarySection.vue'
import CredentialModal from '~/components/repository/CredentialModal.vue'
import EditRepositoryModal from '~/components/repository/EditRepositoryModal.vue'
import ExclusionRulesPanel from '~/components/repository/ExclusionRulesPanel.vue'
import ReconcilePanel from '~/components/repository/ReconcilePanel.vue'
import RepositoryKnowledgeHub from '~/components/repository/RepositoryKnowledgeHub.vue'
import SddMethodologyBadge from '~/components/repository/SddMethodologyBadge.vue'
import SensitiveSuggestionsPanel from '~/components/repository/SensitiveSuggestionsPanel.vue'
import SpaceMultiSelect from '~/components/repository/SpaceMultiSelect.vue'
import WebhookConfigPanel from '~/components/repository/WebhookConfigPanel.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { PLATFORM_LABELS } from '~/types'

const route = useRoute('/repositories/[id]/')
const router = useRouter()
const repositoriesStore = useRepositoriesStore()
const { handleError } = useErrorHandler()
const { success } = useToast()
const { copy } = useClipboard()

const repositoryId = computed(() => route.params.id)

useHead({
  title: computed(() => repositoriesStore.currentRepository?.name
    ? `${repositoriesStore.currentRepository.name} - Friday AI`
    : '仓库详情 - Friday AI'),
})

// 加载仓库
const loading = ref(true)
const indexStatus = ref<IndexStatusResponse | null>(null)

const branchIndexRows = ref<BranchIndexRow[]>([])
const selectedBranch = ref<string | null>(null)
const rebuildDialogOpen = ref(false)
const rebuildingBranch = ref(false)
let branchIndexPollTimer: ReturnType<typeof setInterval> | null = null

async function loadIndexStatus() {
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

async function loadBranchIndexes() {
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
    const defName = repo?.default_branch ?? null
    selectedBranch.value
      = (defName && names.includes(defName) ? defName : null)
        ?? names[0]
        ?? null
  }
  catch {
    branchIndexRows.value = []
  }
}

function startBranchIndexPolling() {
  if (branchIndexPollTimer)
    return
  branchIndexPollTimer = setInterval(async () => {
    await loadIndexStatus()
    await loadBranchIndexes()
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

onMounted(async () => {
  try {
    await Promise.all([
      repositoriesStore.fetchRepository(repositoryId.value),
      repositoriesStore.fetchCredential(repositoryId.value),
      loadIndexStatus(),
    ])
    await loadBranchIndexes()
    if (indexStatus.value?.index_status === IndexStatus.INDEXING)
      startBranchIndexPolling()
  }
  catch (e: unknown) {
    handleError(e, '加载仓库详情')
  }
  finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (branchIndexPollTimer) {
    clearInterval(branchIndexPollTimer)
    branchIndexPollTimer = null
  }
})

// 删除仓库
const deleteDialogOpen = ref(false)
const deleting = ref(false)

async function handleDelete() {
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
const repository = computed(() => repositoriesStore.currentRepository)
const credential = computed(() => repositoriesStore.currentCredential)

/** 远端 HEAD 所在分支（缓存字段，可能为空） */
const headBranch = computed(() => repository.value?.remote_head_branch || null)

/** 分支排序：HEAD > main/master > 最近索引时间 > 字典序 */
const branchNames = computed(() => {
  const head = headBranch.value
  const rows = [...branchIndexRows.value].sort((a, b) => {
    const group = (r: BranchIndexRow) =>
      r.branch_name === head ? 0 : (r.branch_name === 'main' || r.branch_name === 'master') ? 1 : 2
    const ga = group(a)
    const gb = group(b)
    if (ga !== gb)
      return ga - gb
    const ta = a.last_indexed_at ? new Date(a.last_indexed_at).getTime() : 0
    const tb = b.last_indexed_at ? new Date(b.last_indexed_at).getTime() : 0
    if (ta !== tb)
      return tb - ta
    return a.branch_name.localeCompare(b.branch_name)
  })
  return rows.map(r => r.branch_name)
})

const recommendedBaseBranch = computed(() => {
  const base = branchIndexRows.value.find(r => r.is_base_branch)
  if (base)
    return base.branch_name
  return repository.value?.default_branch ?? null
})

const selectedBranchRow = computed(
  () => branchIndexRows.value.find(r => r.branch_name === selectedBranch.value) ?? null,
)

const indexGlobalBusy = computed(
  () => indexStatus.value?.index_status === IndexStatus.INDEXING,
)

const rebuildConfirmDescription = computed(() => {
  const b = selectedBranch.value ?? '—'
  return `将为分支 ${b} 触发后台重建；全局索引进行中时请勿重复提交。`
})

async function confirmRebuildBranchIndex() {
  if (!repository.value || !selectedBranch.value)
    return
  rebuildingBranch.value = true
  try {
    await repositoriesApi.triggerIndex(repository.value.id, { branch: selectedBranch.value })
    success('已提交重建任务', selectedBranch.value)
    rebuildDialogOpen.value = false
    await loadIndexStatus()
    await loadBranchIndexes()
    startBranchIndexPolling()
  }
  catch (e: unknown) {
    handleError(e, '重建分支索引')
  }
  finally {
    rebuildingBranch.value = false
  }
}

// 编辑仓库
const editDialogOpen = ref(false)

// 关联空间管理弹窗
const spacesDialogOpen = ref(false)
const editingSpaceIds = ref<string[]>([])
const savingSpaces = ref(false)

function openSpacesDialog() {
  editingSpaceIds.value = (repository.value?.spaces ?? []).map(s => s.id)
  spacesDialogOpen.value = true
}

async function saveLinkedSpaces() {
  // #9：允许置空（解绑全部空间）；不再强制至少一个
  savingSpaces.value = true
  try {
    await repositoriesApi.setLinkedSpaces(repositoryId.value, editingSpaceIds.value)
    await repositoriesStore.fetchRepository(repositoryId.value)
    success('已更新关联空间')
    spacesDialogOpen.value = false
  }
  catch (e: unknown) {
    handleError(e, '更新关联空间')
  }
  finally {
    savingSpaces.value = false
  }
}

// 凭证管理弹窗（：替代独立路由页入口）
const credentialModalOpen = ref(false)

async function handleCredentialSaved() {
  await repositoriesStore.fetchCredential(repositoryId.value)
}

const sections = ref<NavSection[]>([
  { id: 'basic-info', label: '基本信息', icon: 'icon-[lucide--info]' },
  { id: 'knowledge-base', label: '知识库', icon: 'icon-[lucide--layers]' },
  { id: 'linked-projects', label: '关联空间', icon: 'icon-[lucide--folder]' },
  { id: 'credential', label: '凭证配置', icon: 'icon-[lucide--key]' },
  { id: 'webhook', label: 'Webhook 自动化', icon: 'icon-[lucide--webhook]' },
  { id: 'exclusions', label: '排除规则', icon: 'icon-[lucide--eye-off]' },
  { id: 'danger-zone', label: '危险操作', icon: 'icon-[lucide--alert-triangle]' },
])

async function handleEditSuccess() {
  editDialogOpen.value = false
  await Promise.all([
    repositoriesStore.fetchRepository(repositoryId.value),
    loadIndexStatus(),
    loadBranchIndexes(),
  ])
  if (indexStatus.value?.index_status === IndexStatus.INDEXING)
    startBranchIndexPolling()
}

// 平台图标映射
const platformIcons: Record<string, string> = {
  github: 'icon-[lucide--github]',
  gitlab: 'icon-[simple-icons--gitlab]',
  gitea: 'icon-[simple-icons--gitea]',
  bitbucket: 'icon-[simple-icons--bitbucket]',
}

function copyUrl() {
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
    <LoadingState v-if="loading" variant="skeleton" :count="4" />

    <!-- 仓库详情 -->
    <template v-else-if="repository">
      <!-- ==================== 头部区域 ==================== -->
      <div class="card overflow-hidden">
        <!-- 顶部装饰线 -->
        <div class="h-0.5" />

        <div class="p-5 space-y-4">
          <!-- 第一行：标题 + 操作按钮 -->
          <div class="flex items-start justify-between gap-4">
            <div class="flex items-center gap-3 min-w-0">
              <div class="p-2 rounded-lg bg-primary/10 shrink-0">
                <span class="icon-[lucide--git-branch] text-xl text-primary" />
              </div>
              <div class="min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <h1 class="text-xl font-bold text-foreground truncate">
                    {{ repository.name }}
                  </h1>
                  <Badge variant="outline" class="shrink-0 text-xs">
                    <span :class="platformIcons[repository.git_platform]" class="mr-1" />
                    {{ PLATFORM_LABELS[repository.git_platform] }}
                  </Badge>
                  <Badge variant="secondary" class="shrink-0 font-mono text-xs">
                    <span class="icon-[lucide--git-branch] mr-1 text-[10px]" />
                    {{ repository.default_branch }}
                    <span
                      v-if="headBranch && repository.default_branch === headBranch"
                      class="ml-1.5 rounded-sm bg-emerald-500/15 px-1 py-px text-[9px] font-semibold tracking-wide text-emerald-600"
                    >HEAD</span>
                  </Badge>
                  <SddMethodologyBadge :methodology="repository.methodology" />
                </div>
                <!-- Git URL -->
                <div class="flex items-center gap-1.5 mt-1">
                  <p class="text-xs text-muted-foreground font-mono truncate">
                    {{ repository.git_url }}
                  </p>
                  <TooltipProvider :delay-duration="300">
                    <Tooltip>
                      <TooltipTrigger as-child>
                        <button
                          class="p-0.5 rounded hover:bg-muted/60 transition-colors shrink-0"
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
              <Button variant="outline" size="sm" class="h-8 text-xs" @click="editDialogOpen = true">
                <span class="icon-[lucide--pencil] mr-1.5" />
                编辑
              </Button>
            </div>
          </div>

          <!-- 快速状态指示器（精简：凭证与空间；索引状态见知识库 Hub） -->
          <div class="flex items-center gap-2 pl-[52px] flex-wrap">
            <RouterLink
              to="#knowledge-base"
              class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors cursor-pointer"
              :class="{ 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20 hover:bg-emerald-500/15': indexStatus?.index_status === IndexStatus.INDEXED, 'bg-blue-500/10 text-blue-600 border border-blue-500/20 hover:bg-blue-500/15': indexStatus?.index_status === IndexStatus.INDEXING, 'bg-red-500/10 text-red-600 border border-red-500/20 hover:bg-red-500/15': indexStatus?.index_status === IndexStatus.FAILED, 'bg-muted/60 text-muted-foreground border border-border/50 hover:bg-muted/80': indexStatus?.index_status === IndexStatus.CANCELLED, 'bg-amber-500/10 text-amber-600 border border-amber-500/20 hover:bg-amber-500/15': !indexStatus || indexStatus.index_status === IndexStatus.NOT_INDEXED }"
            >
              <span
                :class="{ 'icon-[lucide--check-circle]': indexStatus?.index_status === IndexStatus.INDEXED, 'icon-[lucide--loader-circle] animate-spin': indexStatus?.index_status === IndexStatus.INDEXING, 'icon-[lucide--x-circle]': indexStatus?.index_status === IndexStatus.FAILED, 'icon-[lucide--circle-stop]': indexStatus?.index_status === IndexStatus.CANCELLED, 'icon-[lucide--layers]': !indexStatus || indexStatus.index_status === IndexStatus.NOT_INDEXED }"
              />
              {{
                indexStatus?.index_status === IndexStatus.INDEXED ? '知识库就绪'
                : indexStatus?.index_status === IndexStatus.INDEXING ? '知识库构建中'
                  : indexStatus?.index_status === IndexStatus.FAILED ? '索引失败'
                    : indexStatus?.index_status === IndexStatus.CANCELLED ? '已停止'
                      : '未建知识库'
              }}
            </RouterLink>

            <div
              class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
              :class="credential ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20' : 'bg-muted/60 text-muted-foreground border border-border/50'"
            >
              <span :class="credential ? 'icon-[lucide--shield-check]' : 'icon-[lucide--shield-off]'" />
              {{ credential ? '凭证已配置' : '未配置凭证' }}
            </div>
            <div class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-muted/60 text-muted-foreground border border-border/50">
              <span class="icon-[lucide--folder]" />
              {{ repository.spaces?.length || 0 }} 个关联空间
            </div>
            <div v-if="repository.proxy_url" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-600 border border-amber-500/20">
              <span class="icon-[lucide--globe]" />
              已配置代理
            </div>
          </div>
        </div>
      </div>

      <AnchorNavLayout :sections="sections">
        <!-- ==================== 基本信息 ==================== -->
        <section id="basic-info" class="scroll-mt-22 space-y-4">
          <div class="card">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
              <span class="icon-[lucide--info] text-primary" />
              <h3 class="text-sm font-semibold">
                仓库信息
              </h3>
            </div>
            <div class="p-5">
              <div class="grid gap-5 sm:grid-cols-2">
                <div>
                  <label class="text-xs text-muted-foreground">Git 平台</label>
                  <p class="text-sm mt-1 font-medium text-foreground">
                    {{ PLATFORM_LABELS[repository.git_platform] }}
                  </p>
                </div>
                <div>
                  <label class="text-xs text-muted-foreground">默认分支</label>
                  <p class="text-sm mt-1 font-mono text-foreground flex items-center gap-1.5">
                    {{ repository.default_branch }}
                    <span
                      v-if="headBranch && repository.default_branch === headBranch"
                      class="rounded-sm bg-emerald-500/15 px-1 py-px text-[9px] font-semibold tracking-wide text-emerald-600"
                    >HEAD</span>
                  </p>
                </div>
                <div v-if="headBranch && repository.default_branch !== headBranch">
                  <label class="text-xs text-muted-foreground">远端 HEAD 分支</label>
                  <p class="text-sm mt-1 font-mono text-foreground flex items-center gap-1.5">
                    {{ headBranch }}
                    <span class="rounded-sm bg-emerald-500/15 px-1 py-px text-[9px] font-semibold tracking-wide text-emerald-600">HEAD</span>
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

          <AISummarySection :repository-id="repository.id" />

          <!-- 关联空间 -->
          <div id="linked-projects" class="card scroll-mt-22">
            <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
              <span class="icon-[lucide--folder] text-primary" />
              <h3 class="text-sm font-semibold">
                关联空间
              </h3>
              <span class="text-xs text-muted-foreground">({{ repository.spaces?.length || 0 }})</span>
              <Button variant="ghost" size="sm" class="h-7 text-xs ml-auto group" @click="openSpacesDialog">
                管理
                <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
              </Button>
            </div>
            <div class="p-5">
              <CompactEmptyState
                v-if="!repository.spaces || repository.spaces.length === 0"
                icon="lucide--folder"
                title="暂无关联空间"
                description="将仓库关联到空间后，可在空间内统一管理与协作"
              >
                <Button size="sm" class="h-7 text-xs" @click="openSpacesDialog">
                  <span class="icon-[lucide--folder-plus] mr-1.5" />
                  关联空间
                </Button>
              </CompactEmptyState>
              <div v-else class="space-y-1.5">
                <RouterLink
                  v-for="space in repository.spaces"
                  :key="space.id"
                  :to="`/spaces/${space.id}`"
                  class="flex items-center justify-between p-2.5 rounded-lg hover:bg-muted/40 transition-colors group"
                >
                  <div class="flex items-center gap-2.5">
                    <div class="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
                      <span class="icon-[lucide--folder-open] text-xs text-primary" />
                    </div>
                    <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ space.name }}</span>
                  </div>
                  <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
                </RouterLink>
              </div>
            </div>
          </div>
        </section>

        <!-- ==================== 知识库（含分支选择器， 合并自分支索引段） ==================== -->
        <section id="knowledge-base" class="scroll-mt-22">
          <RepositoryKnowledgeHub
            v-model:selected-branch="selectedBranch"
            :repository-id="repository.id"
            :git-url="repository.git_url"
            :branches="branchNames"
            :index-rows="branchIndexRows"
            :head-branch="headBranch"
            :recommended-branch="recommendedBaseBranch"
            :selected-branch-row="selectedBranchRow"
            :index-global-busy="indexGlobalBusy"
            :rebuilding-branch="rebuildingBranch"
            @rebuild="rebuildDialogOpen = true"
          />
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
              <Button variant="ghost" size="sm" class="h-7 text-xs group" @click="credentialModalOpen = true">
                管理
                <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
              </Button>
            </div>
            <div class="p-5">
              <div v-if="credential" class="space-y-4">
                <div class="flex items-center gap-2.5">
                  <div class="p-1.5 rounded-full bg-emerald-500/10">
                    <span class="icon-[lucide--check-circle] text-lg text-emerald-500" />
                  </div>
                  <div>
                    <p class="text-sm font-medium text-foreground">
                      凭证已配置
                    </p>
                    <p class="text-xs text-muted-foreground">
                      {{ credential.auth_type === 'ssh_key' ? 'SSH 密钥' : 'Access Token' }}
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
              <CompactEmptyState
                v-else
                icon="lucide--lock"
                title="尚未配置凭证"
                description="配置 SSH 密钥或 Access Token 后即可拉取私有仓库"
              >
                <Button size="sm" class="h-7 text-xs" @click="credentialModalOpen = true">
                  <span class="icon-[lucide--key] mr-1.5" />
                  配置凭证
                </Button>
              </CompactEmptyState>
            </div>
          </div>
        </section>

        <!-- ==================== Webhook 自动化 ==================== -->
        <section id="webhook" class="scroll-mt-22">
          <WebhookConfigPanel :repository="repository" @updated="repositoriesStore.fetchRepository(repositoryId)" />
        </section>

        <!-- ==================== 排除规则（EXCL-01 fail-closed） ==================== -->
        <section id="exclusions" class="scroll-mt-22 space-y-5">
          <ExclusionRulesPanel :repository-id="repository.id" />
          <!-- AI 敏感文件建议（EXCL-03）：建议 + 确认闭环，挂在排除规则面板旁 -->
          <SensitiveSuggestionsPanel :repo-id="repository.id" />
          <!-- 对账 / 清理（EXCL-04 / EXCL-06）：挂在排除规则面板旁 -->
          <ReconcilePanel :repository-id="repository.id" />
        </section>

        <!-- ==================== 危险操作 ==================== -->
        <section id="danger-zone" class="scroll-mt-22">
          <div class="card border-destructive/30 bg-destructive/5">
            <div class="px-5 py-3.5 border-b border-destructive/20 flex items-center gap-2">
              <span class="icon-[lucide--alert-triangle] text-destructive" />
              <h3 class="text-sm font-semibold text-destructive">
                危险操作
              </h3>
            </div>
            <div class="p-5 space-y-4">
              <div class="flex items-start justify-between gap-4">
                <div>
                  <p class="text-sm font-medium text-foreground">
                    删除仓库
                  </p>
                  <p class="text-xs text-muted-foreground mt-1">
                    删除后无法恢复，相关的凭证配置也将被清除。
                  </p>
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
      variant="destructive"
      :loading="deleting"
      @confirm="handleDelete"
    />

    <!-- 编辑对话框 -->
    <EditRepositoryModal
      v-if="repository"
      v-model="editDialogOpen"
      :repository="repository"
      @confirm="handleEditSuccess"
      @cancel="editDialogOpen = false"
      @closed="editDialogOpen = false"
    />

    <!-- 凭证管理弹窗（CRED-02） -->
    <CredentialModal
      v-if="repository"
      v-model:open="credentialModalOpen"
      :repository-id="repository.id"
      :credential="credential"
      @saved="handleCredentialSaved"
    />

    <ConfirmDialog
      v-model:open="rebuildDialogOpen"
      title="确认重建此分支索引？"
      :description="rebuildConfirmDescription"
      confirm-text="确认重建"
      :loading="rebuildingBranch"
      @confirm="confirmRebuildBranchIndex"
    />

    <!-- 管理关联空间 -->
    <Dialog v-model:open="spacesDialogOpen">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>管理关联空间</DialogTitle>
          <DialogDescription>
            可不关联空间（孤儿仓库仅系统管理员可见）；关联后可在空间内统一管理与协作
          </DialogDescription>
        </DialogHeader>
        <div class="py-2">
          <SpaceMultiSelect v-model="editingSpaceIds" :disabled="savingSpaces" />
          <p v-if="editingSpaceIds.length === 0" class="mt-2 text-xs text-muted-foreground flex items-center gap-1">
            <span class="icon-[lucide--info]" />
            未关联任何空间：仅系统管理员可见与管理
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" :disabled="savingSpaces" @click="spacesDialogOpen = false">
            取消
          </Button>
          <Button :disabled="savingSpaces" @click="saveLinkedSpaces">
            <span v-if="savingSpaces" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
