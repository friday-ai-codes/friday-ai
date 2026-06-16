<script setup lang="ts">
import type {
  CapabilityNode,
  DomainNode,
  FacetViewResponse,
  KnowledgeTreeResponse,
  RepoCard,
  RepoIndexTreeResponse,
  TreeSearchResult,
} from '~/api/repoTree'
import { useHead } from '@vueuse/head'
import repoTreeApi from '~/api/repoTree'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CapabilityTreeNode from '~/components/repository/CapabilityTreeNode.vue'
import DomainTreeNode from '~/components/repository/DomainTreeNode.vue'
import SddMethodologyBadge from '~/components/repository/SddMethodologyBadge.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'

useHead({ title: '知识树 - Friday AI' })

const { handleError } = useErrorHandler()

// ---------- 视角与全局树 ----------
const FACET_VIEWS = ['业务线/产品线', '服务对象', '技术形态', '团队归属', '技术栈', '活跃度'] as const
const currentView = ref<string>('domain')

const loading = ref(true)
const treeData = ref<KnowledgeTreeResponse | null>(null)
const facetData = ref<FacetViewResponse | null>(null)

const repoMap = computed<Record<string, RepoCard>>(() =>
  currentView.value === 'domain'
    ? treeData.value?.repos ?? {}
    : facetData.value?.repos ?? {},
)

async function loadView() {
  loading.value = true
  try {
    if (currentView.value === 'domain') {
      treeData.value = await repoTreeApi.getKnowledgeTree()
    }
    else {
      facetData.value = await repoTreeApi.getFacetView(currentView.value)
      selectedDomain.value = null
    }
  }
  catch (e: unknown) {
    handleError(e, '加载知识树')
  }
  finally {
    loading.value = false
  }
}

onMounted(loadView)
watch(currentView, loadView)

// ---------- 域/分组选择 ----------
const selectedDomain = ref<DomainNode | null>(null)
const selectedFacetGroup = ref<string | null>(null)

const visibleRepoIds = computed<string[]>(() => {
  if (currentView.value === 'domain') {
    if (!selectedDomain.value)
      return []
    const ids: string[] = []
    const walk = (n: DomainNode) => {
      ids.push(...n.repo_ids)
      n.children.forEach(walk)
    }
    walk(selectedDomain.value)
    return ids
  }
  const group = facetData.value?.groups.find(g => g.value === selectedFacetGroup.value)
  return group?.repo_ids ?? []
})

// 分面过滤（任意视角下叠加）
const facetFilters = ref<Record<string, string>>({})

const facetFilterOptions = computed<Record<string, string[]>>(() => {
  const options: Record<string, Set<string>> = {}
  for (const card of Object.values(repoMap.value)) {
    for (const [dim, value] of Object.entries(card.facets ?? {})) {
      if (!options[dim])
        options[dim] = new Set()
      options[dim].add(value)
    }
  }
  return Object.fromEntries(
    Object.entries(options).map(([dim, values]) => [dim, [...values].sort()]),
  )
})

const filteredRepoCards = computed<RepoCard[]>(() => {
  const cards = visibleRepoIds.value
    .map(id => repoMap.value[id])
    .filter((c): c is RepoCard => Boolean(c))
  const active = Object.entries(facetFilters.value).filter(([, v]) => v)
  if (!active.length)
    return cards
  return cards.filter(card =>
    active.every(([dim, value]) => (card.facets ?? {})[dim] === value),
  )
})

// ---------- 单仓能力树下钻 ----------
const selectedRepoId = ref<string | null>(null)
const repoTree = ref<RepoIndexTreeResponse | null>(null)
const repoTreeLoading = ref(false)
const highlightTitles = ref<string[]>([])

async function openRepoTree(repoId: string, highlightPath = '') {
  selectedRepoId.value = repoId
  repoTreeLoading.value = true
  highlightTitles.value = highlightPath ? highlightPath.split(' > ') : []
  try {
    repoTree.value = await repoTreeApi.getRepoIndexTree(repoId)
  }
  catch (e: unknown) {
    handleError(e, '加载仓库能力树')
    repoTree.value = null
  }
  finally {
    repoTreeLoading.value = false
  }
}

// ---------- 树内搜索 ----------
const searchQuery = ref('')
const searchResults = ref<TreeSearchResult[]>([])
const searching = ref(false)
const showSearchPanel = ref(false)

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q)
    return
  searching.value = true
  showSearchPanel.value = true
  try {
    const resp = await repoTreeApi.searchKnowledgeTree(q)
    searchResults.value = resp.results
  }
  catch (e: unknown) {
    handleError(e, '知识树搜索')
  }
  finally {
    searching.value = false
  }
}

function jumpToSearchHit(hit: TreeSearchResult) {
  showSearchPanel.value = false
  openRepoTree(hit.repository_id, hit.node_path)
}

// ---------- 节点动作：复制上下文 ----------
async function copyNodeContext(node: CapabilityNode) {
  if (!repoTree.value)
    return
  const lines = [
    `仓库: ${repoTree.value.name} (${repoTree.value.repository_id})`,
    `能力节点: ${node.title}`,
  ]
  if (node.summary)
    lines.push(`职责: ${node.summary}`)
  if (node.paths?.length)
    lines.push(`目录范围: ${node.paths.join(', ')}`)
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
  }
  catch {
    // clipboard 不可用时静默
  }
}

// ---------- 重建（admin） ----------
const rebuilding = ref(false)
async function triggerRebuild() {
  rebuilding.value = true
  try {
    await repoTreeApi.rebuildKnowledgeTree()
  }
  catch (e: unknown) {
    handleError(e, '触发域树重建')
  }
  finally {
    rebuilding.value = false
  }
}

const indexStatusDot: Record<string, string> = {
  indexed: 'bg-emerald-500',
  indexing: 'bg-blue-500 animate-pulse',
  failed: 'bg-red-500',
  not_indexed: 'bg-amber-500',
}
</script>

<template>
  <PageContainer>
    <PageHeader
      icon="lucide--folder-tree"
      icon-gradient="from-primary/20 to-primary/10"
      icon-color="text-primary"
      title="知识树"
      description="业务域 → 仓库 → 子应用 → 模块 → 能力，逐层下钻定位职责归属"
    >
      <template #actions>
        <Button variant="outline" size="sm" :disabled="rebuilding" @click="triggerRebuild">
          <span class="icon-[lucide--refresh-cw] mr-1.5 h-3.5 w-3.5" :class="rebuilding ? 'animate-spin' : ''" />
          重建域树
        </Button>
      </template>
    </PageHeader>

    <!-- 工具栏：视角切换 + 搜索 -->
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div class="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-muted/40 p-1">
        <button
          class="rounded-md px-3 py-1 text-xs transition-colors"
          :class="currentView === 'domain' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'"
          @click="currentView = 'domain'"
        >
          业务域
        </button>
        <button
          v-for="dim in FACET_VIEWS"
          :key="dim"
          class="rounded-md px-3 py-1 text-xs transition-colors"
          :class="currentView === dim ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'"
          @click="currentView = dim"
        >
          {{ dim }}
        </button>
      </div>

      <div class="relative min-w-64 flex-1">
        <span class="icon-[lucide--search] absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索能力节点，如：消息撤回、批量授权…"
          class="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-primary/30"
          @keydown.enter="doSearch"
        >
      </div>
      <Button size="sm" :disabled="searching" @click="doSearch">
        {{ searching ? '搜索中…' : '搜索' }}
      </Button>
    </div>

    <!-- 搜索结果面板 -->
    <div
      v-if="showSearchPanel"
      class="mb-4 rounded-lg border border-border bg-card p-3"
    >
      <div class="mb-2 flex items-center justify-between">
        <span class="text-sm font-medium">搜索结果（{{ searchResults.length }}）</span>
        <button class="text-xs text-muted-foreground hover:text-foreground" @click="showSearchPanel = false">
          收起
        </button>
      </div>
      <div v-if="!searchResults.length" class="py-4 text-center text-sm text-muted-foreground">
        无命中节点
      </div>
      <div v-else class="max-h-72 space-y-1 overflow-y-auto">
        <button
          v-for="hit in searchResults"
          :key="`${hit.repository_id}-${hit.node_id}`"
          class="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60"
          @click="jumpToSearchHit(hit)"
        >
          <span class="icon-[lucide--locate] mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm">
              <span class="font-medium">{{ hit.repo_name }}</span>
              <span class="text-muted-foreground"> &gt; {{ hit.node_path }}</span>
            </span>
            <span v-if="hit.summary" class="block truncate text-xs text-muted-foreground">{{ hit.summary }}</span>
          </span>
          <span class="shrink-0 text-[10px] text-muted-foreground">{{ hit.score.toFixed(3) }}</span>
        </button>
      </div>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-20 text-muted-foreground">
      <span class="icon-[lucide--loader-2] mr-2 h-5 w-5 animate-spin" /> 加载中…
    </div>

    <div v-else class="grid grid-cols-12 gap-4">
      <!-- 左栏：域树 / 分面分组 -->
      <aside class="col-span-12 rounded-lg border border-border bg-card p-3 md:col-span-3">
        <template v-if="currentView === 'domain'">
          <div v-if="!treeData?.has_tree" class="mb-2 rounded-md bg-amber-500/10 p-2 text-xs text-amber-600 dark:text-amber-300">
            尚未构建业务域树，当前按团队归属兜底分组。可点击「重建域树」由 AI 聚类生成。
          </div>
          <div class="space-y-0.5">
            <DomainTreeNode
              v-for="node in treeData?.tree ?? []"
              :key="node.id"
              :node="node"
              :depth="0"
              :selected-id="selectedDomain?.id ?? null"
              @select="selectedDomain = $event"
            />
          </div>
        </template>
        <template v-else>
          <div class="space-y-0.5">
            <button
              v-for="group in facetData?.groups ?? []"
              :key="group.value"
              class="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors"
              :class="selectedFacetGroup === group.value ? 'bg-primary/10 text-primary' : 'hover:bg-muted/60'"
              @click="selectedFacetGroup = group.value"
            >
              <span class="truncate">{{ group.value }}</span>
              <span class="rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground">{{ group.repo_ids.length }}</span>
            </button>
          </div>
        </template>
      </aside>

      <!-- 中栏：仓库列表 -->
      <section class="col-span-12 rounded-lg border border-border bg-card p-3 md:col-span-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <span class="text-sm font-medium">仓库（{{ filteredRepoCards.length }}）</span>
          <select
            v-for="(values, dim) in facetFilterOptions"
            :key="dim"
            v-model="facetFilters[dim]"
            class="h-6 rounded border border-border bg-background px-1 text-[11px] text-muted-foreground"
          >
            <option value="">
              {{ dim }}（全部）
            </option>
            <option v-for="v in values" :key="v" :value="v">
              {{ v }}
            </option>
          </select>
        </div>

        <div v-if="!filteredRepoCards.length" class="py-8 text-center text-sm text-muted-foreground">
          {{ currentView === 'domain' && !selectedDomain ? '从左侧选择业务域' : '该分组下无仓库' }}
        </div>
        <div v-else class="max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
          <button
            v-for="card in filteredRepoCards"
            :key="card.repo_id"
            class="w-full rounded-lg border p-2.5 text-left transition-colors"
            :class="selectedRepoId === card.repo_id ? 'border-primary/60 bg-primary/5' : 'border-border hover:bg-muted/40'"
            @click="openRepoTree(card.repo_id)"
          >
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 shrink-0 rounded-full" :class="indexStatusDot[card.index_status] ?? 'bg-slate-400'" />
              <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ card.name }}</span>
              <span v-if="card.is_monorepo" class="shrink-0 rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-600 dark:text-violet-300">
                monorepo
              </span>
              <span v-if="!card.has_tree" class="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                无树
              </span>
              <SddMethodologyBadge :methodology="card.facets?.methodology" />
            </div>
            <p v-if="card.overview" class="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {{ card.overview }}
            </p>
          </button>
        </div>
      </section>

      <!-- 右栏：单仓能力树 -->
      <section class="col-span-12 rounded-lg border border-border bg-card p-3 md:col-span-5">
        <div v-if="!selectedRepoId" class="py-8 text-center text-sm text-muted-foreground">
          选择仓库查看能力树
        </div>
        <div v-else-if="repoTreeLoading" class="flex items-center justify-center py-12 text-muted-foreground">
          <span class="icon-[lucide--loader-2] mr-2 h-4 w-4 animate-spin" /> 加载能力树…
        </div>
        <template v-else-if="repoTree">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold">{{ repoTree.name }}</span>
            <span v-if="repoTree.is_monorepo" class="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-600 dark:text-violet-300">
              monorepo
            </span>
            <RouterLink
              :to="`/repositories/${repoTree.repository_id}`"
              class="ml-auto text-xs text-primary hover:underline"
            >
              查看仓库 →
            </RouterLink>
          </div>
          <div v-if="Object.keys(repoTree.facets).length" class="mb-2 flex flex-wrap items-center gap-1">
            <SddMethodologyBadge :methodology="repoTree.facets?.methodology" />
            <template v-for="(value, dim) in repoTree.facets" :key="dim">
              <span
                v-if="!(dim === 'methodology' && value === 'SDD')"
                class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {{ dim }}: {{ value }}
              </span>
            </template>
          </div>
          <div v-if="!repoTree.tree.length" class="py-8 text-center text-sm text-muted-foreground">
            该仓库尚未生成能力树（AI 描述状态: {{ repoTree.ai_summary_status }}）
          </div>
          <div v-else class="max-h-[60vh] space-y-0.5 overflow-y-auto pr-1">
            <CapabilityTreeNode
              v-for="node in repoTree.tree"
              :key="node.node_id"
              :node="node"
              :depth="0"
              :stale-node-ids="repoTree.stale_state?.stale_node_ids ?? []"
              :highlight-titles="highlightTitles"
              @action="copyNodeContext"
            />
          </div>
        </template>
      </section>
    </div>
  </PageContainer>
</template>
