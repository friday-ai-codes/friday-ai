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
import { gsap } from 'gsap'
import { Flip } from 'gsap/Flip'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import repoTreeApi from '~/api/repoTree'
import KnowledgeGraphOverview from '~/components/knowledge/KnowledgeGraphOverview.vue'
import CapabilityTreeNode from '~/components/repository/CapabilityTreeNode.vue'
import SddMethodologyBadge from '~/components/repository/SddMethodologyBadge.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'

gsap.registerPlugin(Flip)

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

// ---------- 下钻状态 ----------
const domainPath = ref<DomainNode[]>([])
const selectedFacetGroup = ref<string | null>(null)
const selectedRepoId = ref<string | null>(null)
const repoTree = ref<RepoIndexTreeResponse | null>(null)
const repoTreeLoading = ref(false)
const highlightTitles = ref<string[]>([])
const overviewMode = ref<'cards' | 'graph'>('cards')
const facetFilters = ref<Record<string, string>>({})

function resetDrill() {
  domainPath.value = []
  selectedFacetGroup.value = null
  selectedRepoId.value = null
  repoTree.value = null
  facetFilters.value = {}
}

async function loadView() {
  loading.value = true
  resetDrill()
  try {
    if (currentView.value === 'domain')
      treeData.value = await repoTreeApi.getKnowledgeTree()
    else
      facetData.value = await repoTreeApi.getFacetView(currentView.value)
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

// ---------- 深链：从总览星图「在知识树查看」跳入指定仓库 / 能力节点 ----------
const route = useRoute()
function applyDeepLink() {
  const repo = route.query.kt_repo
  if (typeof repo === 'string' && repo) {
    const node = typeof route.query.kt_node === 'string' ? route.query.kt_node : ''
    openRepoTree(repo, node)
  }
}
onMounted(applyDeepLink)
watch(() => [route.query.kt_repo, route.query.kt_node], applyDeepLink)

const currentDomain = computed(() => domainPath.value[domainPath.value.length - 1] ?? null)
const rootDomains = computed(() => treeData.value?.tree ?? [])
const childDomains = computed(() => currentDomain.value?.children ?? [])

function deepRepoCount(node: DomainNode): number {
  let n = node.repo_ids.length
  node.children.forEach((c) => {
    n += deepRepoCount(c)
  })
  return n
}

// 当前列表层可见仓库（域：直属仓库；分面：分组仓库）
const visibleRepoIds = computed<string[]>(() => {
  if (currentView.value === 'domain')
    return currentDomain.value ? currentDomain.value.repo_ids : []
  const group = facetData.value?.groups.find(g => g.value === selectedFacetGroup.value)
  return group?.repo_ids ?? []
})

// ---------- 分面过滤 chips ----------
const facetFilterOptions = computed<Record<string, string[]>>(() => {
  const options: Record<string, Set<string>> = {}
  for (const id of visibleRepoIds.value) {
    const card = repoMap.value[id]
    if (!card)
      continue
    for (const [dim, value] of Object.entries(card.facets ?? {})) {
      if (!options[dim])
        options[dim] = new Set()
      options[dim].add(value)
    }
  }
  return Object.fromEntries(
    Object.entries(options)
      .map(([dim, values]) => [dim, [...values].sort()] as [string, string[]])
      .filter(([, values]) => values.length > 1),
  )
})

const filteredRepoCards = computed<RepoCard[]>(() => {
  const cards = visibleRepoIds.value
    .map(id => repoMap.value[id])
    .filter((c): c is RepoCard => Boolean(c))
  const active = Object.entries(facetFilters.value).filter(([, v]) => v)
  if (!active.length)
    return cards
  return cards.filter(card => active.every(([dim, value]) => (card.facets ?? {})[dim] === value))
})

const hasActiveFilters = computed(() => Object.values(facetFilters.value).some(Boolean))

// ---------- 层级与导航 ----------
type LevelKind = 'overview' | 'domain' | 'group' | 'repo'
const levelKind = computed<LevelKind>(() => {
  if (selectedRepoId.value)
    return 'repo'
  if (currentView.value === 'domain')
    return currentDomain.value ? 'domain' : 'overview'
  return selectedFacetGroup.value ? 'group' : 'overview'
})

const depth = computed(() =>
  domainPath.value.length
  + (selectedFacetGroup.value ? 1 : 0)
  + (selectedRepoId.value ? 1 : 0),
)

interface Crumb { label: string, kind: 'root' | 'domain' | 'group' | 'repo', index: number }
const breadcrumbs = computed<Crumb[]>(() => {
  const crumbs: Crumb[] = [
    { label: currentView.value === 'domain' ? '知识树' : currentView.value, kind: 'root', index: -1 },
  ]
  if (currentView.value === 'domain')
    domainPath.value.forEach((d, i) => crumbs.push({ label: d.title, kind: 'domain', index: i }))
  else if (selectedFacetGroup.value)
    crumbs.push({ label: selectedFacetGroup.value, kind: 'group', index: 0 })
  if (selectedRepoId.value && repoTree.value)
    crumbs.push({ label: repoTree.value.name, kind: 'repo', index: -2 })
  return crumbs
})

function enterDomain(node: DomainNode) {
  selectedRepoId.value = null
  repoTree.value = null
  facetFilters.value = {}
  domainPath.value = [...domainPath.value, node]
}

function enterGroup(value: string) {
  selectedRepoId.value = null
  repoTree.value = null
  facetFilters.value = {}
  selectedFacetGroup.value = value
}

function onCrumb(c: Crumb) {
  if (c.kind === 'repo')
    return
  selectedRepoId.value = null
  repoTree.value = null
  facetFilters.value = {}
  if (c.kind === 'root') {
    domainPath.value = []
    selectedFacetGroup.value = null
  }
  else if (c.kind === 'domain') {
    domainPath.value = domainPath.value.slice(0, c.index + 1)
  }
}

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

// ---------- GSAP 转场动效 ----------
const rootEl = ref<HTMLElement | null>(null)
const stageEl = ref<HTMLElement | null>(null)
let ctx: gsap.Context | null = null
let mm: ReturnType<typeof gsap.matchMedia> | null = null
const reduceMotion = ref(false)
let prevDepth = 0

onMounted(() => {
  ctx = gsap.context(() => {}, rootEl.value ?? undefined)
  mm = gsap.matchMedia()
  // 默认允许动效；仅当用户偏好减弱动态时关闭。
  mm.add('(prefers-reduced-motion: reduce)', () => {
    reduceMotion.value = true
  })
})

onUnmounted(() => {
  ctx?.revert()
  mm?.revert()
})

function playStageEntrance(direction: number) {
  if (reduceMotion.value || !stageEl.value || !ctx)
    return
  ctx.add(() => {
    gsap.from(stageEl.value, {
      autoAlpha: 0,
      x: 28 * direction,
      duration: 0.35,
      ease: 'power2.out',
    })
    const cards = stageEl.value!.querySelectorAll('[data-kt-card]')
    if (cards.length) {
      gsap.from(cards, {
        autoAlpha: 0,
        y: 16,
        duration: 0.4,
        stagger: 0.04,
        ease: 'power2.out',
      })
    }
  })
}

watch(
  () => `${currentView.value}|${depth.value}|${levelKind.value}|${selectedRepoId.value ?? ''}|${currentDomain.value?.id ?? ''}|${selectedFacetGroup.value ?? ''}`,
  async () => {
    const dir = depth.value >= prevDepth ? 1 : -1
    prevDepth = depth.value
    await nextTick()
    playStageEntrance(dir)
  },
)

// 分面 chips：用 Flip 让仓库卡片重排丝滑过渡
function setFacetFilter(dim: string, value: string) {
  const grid = stageEl.value?.querySelector('[data-kt-repo-grid]')
  const cards = grid?.querySelectorAll('[data-kt-card]')
  const state = !reduceMotion.value && cards && cards.length ? Flip.getState(cards) : null

  if (value)
    facetFilters.value = { ...facetFilters.value, [dim]: value }
  else
    facetFilters.value = Object.fromEntries(Object.entries(facetFilters.value).filter(([k]) => k !== dim))

  if (state) {
    nextTick(() => {
      ctx?.add(() => {
        Flip.from(state, {
          duration: 0.4,
          ease: 'power2.inOut',
          stagger: 0.02,
          absolute: true,
          onEnter: els => gsap.fromTo(els, { autoAlpha: 0, scale: 0.9 }, { autoAlpha: 1, scale: 1, duration: 0.3 }),
          onLeave: els => gsap.to(els, { autoAlpha: 0, scale: 0.9, duration: 0.2 }),
        })
      })
    })
  }
}

function clearFacetFilters() {
  facetFilters.value = {}
}
</script>

<template>
  <div ref="rootEl">
    <!-- 工具栏：视角切换 + 搜索 + 重建 -->
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
      <!-- 总览的「卡片 / 图谱」切换（仅根层显示） -->
      <div
        v-if="currentView === 'domain' && levelKind === 'overview'"
        class="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-1"
      >
        <button
          class="flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors"
          :class="overviewMode === 'cards' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'"
          @click="overviewMode = 'cards'"
        >
          <span class="icon-[lucide--layout-grid] h-3.5 w-3.5" /> 卡片
        </button>
        <button
          class="flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors"
          :class="overviewMode === 'graph' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'"
          @click="overviewMode = 'graph'"
        >
          <span class="icon-[lucide--share-2] h-3.5 w-3.5" /> 图谱
        </button>
      </div>
      <Button variant="outline" size="sm" :disabled="rebuilding" @click="triggerRebuild">
        <span class="icon-[lucide--refresh-cw] mr-1.5 h-3.5 w-3.5" :class="rebuilding ? 'animate-spin' : ''" />
        重建域树
      </Button>
    </div>

    <!-- 面包屑 -->
    <nav v-if="breadcrumbs.length > 1" class="mb-3 flex items-center gap-1 overflow-x-auto text-sm scrollbar-hide">
      <template v-for="(c, i) in breadcrumbs" :key="i">
        <span v-if="i > 0" class="icon-[lucide--chevron-right] h-4 w-4 shrink-0 text-muted-foreground/60" />
        <button
          class="shrink-0 whitespace-nowrap rounded-md px-1.5 py-0.5 transition-colors"
          :class="c.kind === 'repo'
            ? 'font-medium text-foreground cursor-default'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          :disabled="c.kind === 'repo'"
          @click="onCrumb(c)"
        >
          {{ c.label }}
        </button>
      </template>
    </nav>

    <!-- 搜索结果面板 -->
    <div v-if="showSearchPanel" class="mb-4 rounded-lg border border-border bg-card p-3">
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

    <!-- 加载 -->
    <div v-if="loading" class="flex items-center justify-center py-20 text-muted-foreground">
      <span class="icon-[lucide--loader-2] mr-2 h-5 w-5 animate-spin" /> 加载中…
    </div>

    <!-- 内容舞台 -->
    <div v-else ref="stageEl">
      <!-- ============ 仓库能力树（细节按需） ============ -->
      <section v-if="levelKind === 'repo'" class="rounded-xl border border-border bg-card p-4">
        <div v-if="repoTreeLoading" class="flex items-center justify-center py-12 text-muted-foreground">
          <span class="icon-[lucide--loader-2] mr-2 h-4 w-4 animate-spin" /> 加载能力树…
        </div>
        <template v-else-if="repoTree">
          <div class="mb-3 flex flex-wrap items-center gap-2">
            <span class="text-base font-semibold">{{ repoTree.name }}</span>
            <span v-if="repoTree.is_monorepo" class="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-600 dark:text-violet-300">
              monorepo
            </span>
            <SddMethodologyBadge :methodology="repoTree.facets?.methodology" />
            <RouterLink
              :to="`/repositories/${repoTree.repository_id}`"
              class="ml-auto text-xs text-primary hover:underline"
            >
              查看仓库 →
            </RouterLink>
          </div>
          <div v-if="Object.keys(repoTree.facets).length" class="mb-3 flex flex-wrap items-center gap-1">
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
          <div v-else class="max-h-[64vh] space-y-0.5 overflow-y-auto pr-1">
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

      <!-- ============ 总览：图谱模式 ============ -->
      <KnowledgeGraphOverview
        v-else-if="currentView === 'domain' && levelKind === 'overview' && overviewMode === 'graph'"
        :domains="rootDomains"
        :repo-map="repoMap"
        @enter-domain="enterDomain"
        @open-repo="openRepoTree($event)"
      />

      <!-- ============ 总览/域详情/分组：卡片 ============ -->
      <template v-else>
        <!-- 业务域未建提示 -->
        <div
          v-if="currentView === 'domain' && levelKind === 'overview' && !treeData?.has_tree"
          class="mb-3 rounded-md bg-amber-500/10 p-2.5 text-xs text-amber-600 dark:text-amber-300"
        >
          尚未构建业务域树，当前按团队归属兜底分组。可点击「重建域树」由 AI 聚类生成。
        </div>

        <!-- 域卡片网格（域总览 + 子域） -->
        <div
          v-if="(currentView === 'domain' && (levelKind === 'overview' || childDomains.length))"
          class="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
        >
          <button
            v-for="node in (levelKind === 'overview' ? rootDomains : childDomains)"
            :key="node.id"
            data-kt-card
            class="card card-interactive group flex flex-col p-4 text-left"
            @click="enterDomain(node)"
          >
            <div class="flex items-center gap-2.5">
              <div class="shrink-0 rounded-lg bg-primary/10 p-1.5">
                <span class="icon-[lucide--folder-tree] text-base text-primary" />
              </div>
              <span class="min-w-0 flex-1 truncate text-sm font-semibold group-hover:text-primary transition-colors">{{ node.title }}</span>
              <span class="icon-[lucide--chevron-right] h-4 w-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <p v-if="node.summary" class="mt-2 line-clamp-2 text-xs text-muted-foreground">
              {{ node.summary }}
            </p>
            <div class="mt-3 flex items-center gap-3 text-[11px] text-muted-foreground">
              <span class="inline-flex items-center gap-1"><span class="icon-[lucide--git-branch] text-primary/60" /> {{ deepRepoCount(node) }} 仓库</span>
              <span v-if="node.children.length" class="inline-flex items-center gap-1"><span class="icon-[lucide--layers] text-primary/60" /> {{ node.children.length }} 子域</span>
            </div>
          </button>
        </div>

        <!-- 分组卡片网格（分面视角总览） -->
        <div
          v-else-if="currentView !== 'domain' && levelKind === 'overview'"
          class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
        >
          <button
            v-for="group in facetData?.groups ?? []"
            :key="group.value"
            data-kt-card
            class="card card-interactive group flex items-center justify-between gap-2 p-4 text-left"
            @click="enterGroup(group.value)"
          >
            <span class="min-w-0 flex-1 truncate text-sm font-semibold group-hover:text-primary transition-colors">{{ group.value }}</span>
            <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{{ group.repo_ids.length }} 仓库</span>
          </button>
        </div>

        <!-- 仓库卡片列表（域详情 / 分组详情） -->
        <div v-if="levelKind === 'domain' || levelKind === 'group'">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <span class="text-sm font-medium">仓库（{{ filteredRepoCards.length }}）</span>
            <button
              v-if="hasActiveFilters"
              class="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              @click="clearFacetFilters"
            >
              <span class="icon-[lucide--x] h-3 w-3" /> 清除筛选
            </button>
          </div>

          <div
            v-for="(values, dim) in facetFilterOptions"
            :key="dim"
            class="mb-1.5 flex flex-wrap items-center gap-1"
          >
            <span class="mr-0.5 shrink-0 text-[11px] font-medium text-muted-foreground">{{ dim }}</span>
            <button
              class="rounded-full border px-2 py-0.5 text-[11px] transition-colors"
              :class="!facetFilters[dim] ? 'border-primary/60 bg-primary/10 text-primary font-medium' : 'border-border text-muted-foreground hover:bg-muted/60'"
              @click="setFacetFilter(dim, '')"
            >
              全部
            </button>
            <button
              v-for="v in values"
              :key="v"
              class="rounded-full border px-2 py-0.5 text-[11px] transition-colors"
              :class="facetFilters[dim] === v ? 'border-primary/60 bg-primary/10 text-primary font-medium' : 'border-border text-muted-foreground hover:bg-muted/60'"
              @click="setFacetFilter(dim, v)"
            >
              {{ v }}
            </button>
          </div>

          <div v-if="!filteredRepoCards.length" class="py-10 text-center text-sm text-muted-foreground">
            该层暂无仓库
          </div>
          <div v-else data-kt-repo-grid class="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <button
              v-for="card in filteredRepoCards"
              :key="card.repo_id"
              data-kt-card
              class="card card-interactive group flex flex-col p-4 text-left"
              @click="openRepoTree(card.repo_id)"
            >
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 shrink-0 rounded-full" :class="indexStatusDot[card.index_status] ?? 'bg-slate-400'" />
                <span class="min-w-0 flex-1 truncate text-sm font-semibold group-hover:text-primary transition-colors">{{ card.name }}</span>
                <span v-if="card.is_monorepo" class="shrink-0 rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-600 dark:text-violet-300">monorepo</span>
                <span v-if="!card.has_tree" class="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">无树</span>
                <SddMethodologyBadge :methodology="card.facets?.methodology" />
              </div>
              <p v-if="card.overview" class="mt-2 line-clamp-2 text-xs text-muted-foreground">
                {{ card.overview }}
              </p>
            </button>
          </div>
        </div>

        <!-- 域详情但既无子域也无直属仓库 -->
        <div
          v-if="levelKind === 'domain' && !childDomains.length && !visibleRepoIds.length"
          class="py-10 text-center text-sm text-muted-foreground"
        >
          该业务域下暂无仓库
        </div>
      </template>
    </div>
  </div>
</template>
