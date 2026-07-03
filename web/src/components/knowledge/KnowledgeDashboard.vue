<script setup lang="ts">
/**
 * 知识「总览」仪表盘
 *
 * 把原本散落在各 Tab 里的体量铺开成一屏可感知的全景：核心指标、索引健康、
 * 业务域亮点、分面分布、快捷入口。数据全部由单次 `getKnowledgeTree()` 派生，
 * 无额外请求（repo card 已自带 facets/index_status）。
 */
import type { ArtifactView } from '~/api/artifacts'
import type { ArtifactOverviewItem } from '~/api/knowledge'
import type { DomainNode, RepoCard } from '~/api/repoTree'
import type { CloudTerm, KnowledgeSearchItem, StarNode } from '~/composables/useKnowledgeCapabilities'
import { useQuery } from '@tanstack/vue-query'
import { gsap } from 'gsap'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { knowledgeApi } from '~/api'
import { artifactsApi } from '~/api/artifacts'
import repoTreeApi from '~/api/repoTree'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import FeishuLogo from '~/components/common/FeishuLogo.vue'
import FeishuSheetLogo from '~/components/common/FeishuSheetLogo.vue'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import KnowledgeSearchBar from '~/components/knowledge/KnowledgeSearchBar.vue'
import KnowledgeStarfield3D from '~/components/knowledge/KnowledgeStarfield3D.vue'
import KnowledgeWordCloud from '~/components/knowledge/KnowledgeWordCloud.vue'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import Pagination from '~/components/ui/pagination/Pagination.vue'
import { Skeleton } from '~/components/ui/skeleton'
import { useKnowledgeCapabilities } from '~/composables/useKnowledgeCapabilities'

type KnowledgeTab = 'overview' | 'tree' | 'ingest' | 'search'

const emit = defineEmits<{
  (e: 'navigate', tab: KnowledgeTab): void
}>()

const { t } = useI18n()
const router = useRouter()
const route = useRoute()

const treeQuery = useQuery({
  queryKey: ['knowledge', 'tree', 'overview'],
  queryFn: () => repoTreeApi.getKnowledgeTree(),
  staleTime: 60_000,
})

const data = computed(() => treeQuery.data.value ?? null)
const repos = computed<RepoCard[]>(() => Object.values(data.value?.repos ?? {}))
const isLoading = computed(() => treeQuery.isLoading.value)
const isEmpty = computed(() => !isLoading.value && repos.value.length === 0)

// ---------- 业务域计数（递归） ----------
function deepRepoCount(node: DomainNode): number {
  return node.repo_ids.length + node.children.reduce((n, c) => n + deepRepoCount(c), 0)
}
function countDomains(nodes: DomainNode[]): number {
  return nodes.reduce((n, d) => n + 1 + countDomains(d.children), 0)
}

const rootDomains = computed(() => data.value?.tree ?? [])
const domainCount = computed(() => countDomains(rootDomains.value))

// ---------- 核心指标 ----------
const totalRepos = computed(() => data.value?.total_repos ?? repos.value.length)
const treedRepos = computed(() => repos.value.filter(r => r.has_tree).length)
const monorepoCount = computed(() => repos.value.filter(r => r.is_monorepo).length)
const indexedRepos = computed(() => repos.value.filter(r => r.index_status === 'indexed').length)
const coveragePct = computed(() =>
  repos.value.length ? Math.round((treedRepos.value / repos.value.length) * 100) : 0,
)
const indexedPct = computed(() =>
  repos.value.length ? Math.round((indexedRepos.value / repos.value.length) * 100) : 0,
)

// ---------- 索引健康分布 ----------
const INDEX_META: Record<string, { label: string, dot: string, bar: string }> = {
  indexed: { label: '已索引', dot: 'bg-emerald-500', bar: 'bg-emerald-500' },
  indexing: { label: '索引中', dot: 'bg-blue-500', bar: 'bg-blue-500' },
  failed: { label: '失败', dot: 'bg-red-500', bar: 'bg-red-500' },
  not_indexed: { label: '未索引', dot: 'bg-amber-500', bar: 'bg-amber-500' },
}
const INDEX_ORDER = ['indexed', 'indexing', 'failed', 'not_indexed']

// 运行状态明细：保留全部状态（含 0），用于状态分解列表
const statusBreakdown = computed(() => {
  const counts: Record<string, number> = {}
  for (const r of repos.value)
    counts[r.index_status] = (counts[r.index_status] ?? 0) + 1
  const total = repos.value.length || 1
  return INDEX_ORDER.map(status => ({
    status,
    meta: INDEX_META[status] ?? { label: status, dot: 'bg-slate-400', bar: 'bg-slate-400' },
    count: counts[status] ?? 0,
    pct: Math.round(((counts[status] ?? 0) / total) * 100),
  }))
})

// ---------- 业务域亮点（按仓库体量排序取前若干） ----------
const domainHighlights = computed(() =>
  [...rootDomains.value]
    .map(d => ({ node: d, repos: deepRepoCount(d) }))
    .sort((a, b) => b.repos - a.repos)
    .slice(0, 8),
)

// ---------- 分面分布（从 repo card facets 聚合） ----------
interface FacetValue { value: string, count: number, pct: number }
interface FacetDimension { dim: string, total: number, values: FacetValue[] }

const facetDimensions = computed<FacetDimension[]>(() => {
  const dims: Record<string, Record<string, number>> = {}
  for (const r of repos.value) {
    for (const [dim, value] of Object.entries(r.facets ?? {})) {
      if (dim === 'methodology' || !value)
        continue
      dims[dim] ??= {}
      dims[dim][value] = (dims[dim][value] ?? 0) + 1
    }
  }
  return Object.entries(dims)
    .map(([dim, valueCounts]) => {
      const entries = Object.entries(valueCounts)
      const total = entries.reduce((n, [, c]) => n + c, 0)
      const values = entries
        .map(([value, count]) => ({ value, count, pct: Math.round((count / (total || 1)) * 100) }))
        .sort((a, b) => b.count - a.count)
      return { dim, total, values }
    })
    .filter(d => d.values.length > 1)
    .sort((a, b) => b.values.length - a.values.length)
})

// ---------- 业务域排行（条形榜）----------
const domainMaxRepos = computed(() =>
  Math.max(1, ...domainHighlights.value.map(d => d.repos)),
)

// ---------- 分面透视（按维度切换分布）----------
const selectedFacetDim = ref<string | null>(null)
const activeFacet = computed(() => {
  const dims = facetDimensions.value
  if (!dims.length)
    return null
  return dims.find(d => d.dim === selectedFacetDim.value) ?? dims[0]
})
const facetMax = computed(() =>
  Math.max(1, ...(activeFacet.value?.values.map(v => v.count) ?? [1])),
)

// ---------- 真实业务维度：仓库能力树聚合（星图节点/连线 + 词云词条） ----------
const capsEnabled = computed(() => !isLoading.value && !isEmpty.value)
const caps = useKnowledgeCapabilities(repos, capsEnabled)

const starNodes = computed(() => caps.nodes.value)
const starLinks = computed(() => caps.links.value)
const cloudTerms = computed<CloudTerm[]>(() => caps.terms.value)
const searchItems = computed<KnowledgeSearchItem[]>(() => caps.items.value)
const capabilityCount = computed(() => caps.capabilityCount.value)
const capsLoading = computed(() => caps.isLoading.value)
const capsReady = computed(() => caps.hasData.value)

// 词云去重词条数（小卡片底部统计）
const keywordCount = computed(() => cloudTerms.value.length)

// ---------- 弹窗详情 ----------
const starfieldOpen = ref(false)
const cloudOpen = ref(false)

// 展开动画：先放 GSAP 过渡，再延后挂载重型 3D（避免同步初始化阻塞动画造成卡顿）
const starfieldMount = ref(false)
const starModalEl = ref<HTMLElement | null>(null)
const starStageEl = ref<HTMLElement | null>(null)

const prefersReducedMotion = typeof window !== 'undefined'
  && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

watch(starfieldOpen, (open) => {
  if (!open) {
    starfieldMount.value = false
    return
  }
  starfieldMount.value = false
  nextTick(() => {
    // 1) GSAP 弹窗展开过渡（缩放 + 上浮 + 渐显，头部分项错落进入）
    if (starModalEl.value && !prefersReducedMotion) {
      gsap.killTweensOf(starModalEl.value)
      gsap.fromTo(
        starModalEl.value,
        { autoAlpha: 0, scale: 0.9, y: 28 },
        { autoAlpha: 1, scale: 1, y: 0, duration: 0.5, ease: 'expo.out' },
      )
      const items = starModalEl.value.querySelectorAll('[data-anim]')
      if (items.length) {
        gsap.from(items, {
          autoAlpha: 0,
          y: 12,
          duration: 0.4,
          stagger: 0.07,
          ease: 'power2.out',
          delay: 0.14,
        })
      }
    }
    // 2) 动画结束后再挂载 3D，并淡入舞台
    const delay = prefersReducedMotion ? 0 : 420
    window.setTimeout(() => {
      starfieldMount.value = true
      nextTick(() => {
        if (starStageEl.value && !prefersReducedMotion)
          gsap.from(starStageEl.value, { autoAlpha: 0, duration: 0.6, ease: 'power2.out' })
      })
    }, delay)
  })
})

// 统一跳转：仓库 → 仓库页；能力/模块 → 知识树并高亮（路径 = 祖先 > 自身）
function goToKnowledge(opts: { kind: string, repoId?: string, trail?: string[], title: string }) {
  if (opts.kind === 'repo' && opts.repoId) {
    router.push(`/repositories/${opts.repoId}`)
    return
  }
  const path = [...(opts.trail ?? []), opts.title].join(' > ')
  router.push({ query: { tab: 'tree', kt_repo: opts.repoId ?? '', kt_node: path } })
}

function onStarOpen(node: StarNode) {
  starfieldOpen.value = false
  goToKnowledge({ kind: node.group, repoId: node.repoId, trail: node.trail, title: node.label })
}

function onSearchSelect(item: KnowledgeSearchItem) {
  goToKnowledge({ kind: item.kind, repoId: item.repoId, trail: item.trail, title: item.title })
}

function onCloudPick() {
  cloudOpen.value = false
  emit('navigate', 'tree')
}

// ---------- 交付文档 / 外部依赖（KDEP-03，服务端分页 + 排序）----------
// 分页大小；页码写入 URL（?dep_page=），刷新/前进后退可复原（对齐仓库/执行列表的 URL 状态范式）。
const DEP_PAGE_SIZE = 20
const depPage = computed(() => {
  const raw = Number(route.query.dep_page)
  return Number.isFinite(raw) && raw >= 1 ? Math.floor(raw) : 1
})
function setDepPage(p: number) {
  router.replace({ query: { ...route.query, dep_page: p > 1 ? String(p) : undefined } })
}

const overviewQuery = useQuery({
  queryKey: ['knowledge', 'artifact-overview', depPage],
  queryFn: () => knowledgeApi.getArtifactOverview({ page: depPage.value, pageSize: DEP_PAGE_SIZE }),
  staleTime: 60_000,
  // 翻页时保留上一页数据，避免骨架闪烁。
  placeholderData: prev => prev,
})
const depTypes = computed(() => overviewQuery.data.value?.types ?? [])
const depItems = computed(() => overviewQuery.data.value?.items ?? [])
const depTotal = computed(() => overviewQuery.data.value?.total ?? 0)
const depLoading = computed(() => overviewQuery.isLoading.value)
const depEmpty = computed(() => !depLoading.value && depTotal.value === 0)

// 区块内即时搜索：客户端过滤**当前页**已加载条目（跨页搜索请用知识搜索 Tab）。
const depSearch = ref('')
const filteredDepItems = computed(() => {
  const q = depSearch.value.trim().toLowerCase()
  if (!q)
    return depItems.value
  return depItems.value.filter(i =>
    i.title.toLowerCase().includes(q)
    || depTypeLabel(i.type_key, i.type_name).toLowerCase().includes(q)
    || i.project_name.toLowerCase().includes(q),
  )
})

// 载体图标 + 品牌色：飞书文档（蓝）/ 飞书表格（绿）/ markdown（真 logo）各自区分。
// 颜色类以字面量写在此处，确保被 Tailwind 扫描生成（动态 :class 绑定不影响扫描）。
const DEP_CARRIER: Record<string, { icon: string, color: string }> = {
  feishu_doc: { icon: 'lucide--file-text', color: 'text-blue-500' },
  feishu_bitable: { icon: 'lucide--table', color: 'text-emerald-500' },
  markdown: { icon: 'simple-icons--markdown', color: 'text-foreground/70' },
  external_link: { icon: 'lucide--link', color: 'text-violet-500' },
  repo_file: { icon: 'lucide--file-code', color: 'text-amber-500' },
}
function depCarrier(carrier: string): { icon: string, color: string } {
  return DEP_CARRIER[carrier] ?? { icon: 'lucide--file', color: 'text-muted-foreground' }
}

// 类型中文标签：内置类型直接命中；自定义/英文 key（如 Retro / PRD）归一到中文标签，兜底 type_name。
const DEP_TYPE_LABEL: Record<string, string> = {
  requirement_doc: '需求文档',
  prd: '需求文档',
  feature_list: 'Feature List',
  dev_spec: '研发 Spec',
  ui_design: 'UI 稿',
  ui_review: 'UI 评审',
  tracking_doc: '埋点文档',
  tracking_review: '埋点评审',
  retrospective: '复盘',
  retro: '复盘',
}
function depTypeLabel(typeKey: string, typeName: string): string {
  const k = (typeKey || '').toLowerCase()
  if (DEP_TYPE_LABEL[k])
    return DEP_TYPE_LABEL[k]
  if (k.includes('retro'))
    return '复盘'
  if (k.includes('prd') || k.includes('requirement'))
    return '需求文档'
  if (k.includes('spec'))
    return '研发 Spec'
  if (k.includes('tech') || k.includes('solution'))
    return '技术方案'
  if (k.includes('test') || k.includes('case'))
    return '测试用例'
  if (k.includes('track'))
    return '埋点文档'
  if (k === 'ui' || k.includes('ui_') || k.includes('design'))
    return 'UI 稿'
  return typeName || typeKey
}

// 类型标签配色（放标题前的 tag）：按中文类别给不同颜色；字面量类名供 Tailwind 扫描。
function depTypeColor(typeKey: string, typeName: string): string {
  switch (depTypeLabel(typeKey, typeName)) {
    case '需求文档':
      return 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
    case '研发 Spec':
      return 'bg-violet-500/10 text-violet-600 dark:text-violet-400'
    case 'UI 稿':
      return 'bg-pink-500/10 text-pink-600 dark:text-pink-400'
    case 'UI 评审':
      return 'bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-400'
    case '埋点文档':
      return 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
    case '埋点评审':
      return 'bg-orange-500/10 text-orange-600 dark:text-orange-400'
    case '技术方案':
      return 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400'
    case '测试用例':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
    case '复盘':
      return 'bg-rose-500/10 text-rose-600 dark:text-rose-400'
    case 'Feature List':
      return 'bg-teal-500/10 text-teal-600 dark:text-teal-400'
    default:
      return 'bg-slate-500/10 text-slate-600 dark:text-slate-400'
  }
}

// markdown 内联预览（走工件在线查看接口，取 content 渲染）；飞书/外链直接新窗口打开。
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('')
const previewData = ref<ArtifactView | null>(null)
async function openInlinePreview(item: ArtifactOverviewItem) {
  previewTitle.value = item.title
  previewData.value = null
  previewOpen.value = true
  previewLoading.value = true
  try {
    previewData.value = await artifactsApi.view(item.project_id, item.artifact_id)
  }
  catch {
    previewData.value = {
      artifact_id: item.artifact_id,
      carrier: item.carrier as ArtifactView['carrier'],
      title: item.title,
      url: item.url,
      version: 1,
      render_type: 'unknown',
      error: t('projects.artifacts.viewFailed'),
    }
  }
  finally {
    previewLoading.value = false
  }
}

// 点某类型 → 跳搜索 Tab 预筛该类型（?dep_type= 预填，供搜索侧消费）。
function goToDepType(typeKey: string) {
  router.push({ query: { tab: 'search', dep_type: typeKey } })
}

// 条目点击：markdown 内联预览；飞书文档/表格/外链直接新窗口打开对应地址；其余跳搜索 Tab。
function openDepItem(item: ArtifactOverviewItem) {
  if (item.carrier === 'markdown') {
    void openInlinePreview(item)
    return
  }
  if (item.url) {
    window.open(item.url, '_blank', 'noopener,noreferrer')
    return
  }
  emit('navigate', 'search')
}
</script>

<template>
  <div class="space-y-6">
    <!-- ============ 加载骨架 ============ -->
    <template v-if="isLoading">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Skeleton v-for="n in 4" :key="n" class="h-[92px] w-full rounded-2xl" />
      </div>
      <Skeleton class="h-40 w-full rounded-2xl" />
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton v-for="n in 6" :key="n" class="h-32 w-full rounded-2xl" />
      </div>
    </template>

    <!-- ============ 全局空态（仅当仓库与交付文档皆空时才占位） ============ -->
    <div v-else-if="isEmpty && depEmpty && !depLoading" class="flex min-h-[420px] items-center justify-center">
      <CompactEmptyState
        icon="icon-[lucide--book-open]"
        :title="t('knowledge.overview.empty.title')"
        :description="t('knowledge.overview.empty.body')"
      />
    </div>

    <!-- ============ 总览正文 ============ -->
    <template v-else>
      <!-- 仓库派生内容：仅当存在纳管仓库时渲染（交付文档区块与仓库存在性解耦，见下方独立 section） -->
      <template v-if="!isEmpty">
        <!-- 知识库搜索（仓库 / 能力 / 关键词） -->
        <KnowledgeSearchBar :items="searchItems" :loading="capsLoading" @select="onSearchSelect" />

        <!-- 核心指标（扁平磁贴：纯色 tint 图标块 + 底部 accent 线，无渐变/位移/阴影） -->
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div
            v-for="stat in [
              { key: 'repos', icon: 'icon-[lucide--git-branch]', value: totalRepos, label: t('knowledge.overview.stats.repos'), chip: 'bg-primary/10 text-primary', bar: 'bg-primary' },
              { key: 'domains', icon: 'icon-[lucide--folder-tree]', value: domainCount, label: t('knowledge.overview.stats.domains'), chip: 'bg-violet-500/10 text-violet-600 dark:text-violet-400', bar: 'bg-violet-500' },
              { key: 'capabilities', icon: 'icon-[lucide--box]', value: capabilityCount, label: t('knowledge.overview.stats.capabilities'), chip: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400', bar: 'bg-emerald-500' },
              { key: 'keywords', icon: 'icon-[lucide--hash]', value: keywordCount, label: t('knowledge.overview.stats.keywords'), chip: 'bg-amber-500/10 text-amber-600 dark:text-amber-400', bar: 'bg-amber-500' },
            ]"
            :key="stat.key"
            class="group relative overflow-hidden rounded-xl border border-border bg-card p-4 transition-colors duration-200 hover:border-primary/35"
          >
            <div class="flex items-center gap-3.5">
              <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg" :class="stat.chip">
                <span :class="stat.icon" class="text-xl" />
              </div>
              <div class="min-w-0">
                <p class="text-[26px] font-bold leading-none tracking-tight tabular-nums">
                  {{ stat.value }}
                </p>
                <p class="mt-1.5 truncate text-xs text-muted-foreground">
                  {{ stat.label }}
                </p>
              </div>
            </div>
            <!-- 扁平 accent：底部细色条，hover 加宽呼应而非投影位移 -->
            <span
              class="absolute inset-x-0 bottom-0 h-[3px] origin-left scale-x-[0.35] transition-transform duration-300 group-hover:scale-x-100"
              :class="stat.bar"
            />
          </div>
        </div>

        <!-- 业务能力全景 -->
        <section>
          <div class="mb-3 flex items-center gap-2.5">
            <span class="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary">
              <span class="icon-[lucide--telescope] text-[13px]" />
            </span>
            <h3 class="text-sm font-semibold tracking-wide">
              {{ t('knowledge.overview.panorama.title') }}
            </h3>
            <span class="h-3.5 w-px bg-border" />
            <span class="text-xs text-muted-foreground">{{ t('knowledge.overview.panorama.hint') }}</span>
          </div>

          <div class="grid gap-4 lg:grid-cols-5">
            <!-- 知识星图（小卡：旋转预览，点「展开」看大图 / 拖拽即可交互） -->
            <div class="flex flex-col overflow-hidden rounded-xl border border-indigo-500/25 bg-[#0a0a1f] lg:col-span-3">
              <header class="flex items-center gap-3 px-4 py-3">
                <div class="shrink-0 rounded-xl bg-indigo-500/15 p-2 ring-1 ring-inset ring-indigo-400/20">
                  <span class="icon-[lucide--orbit] text-lg text-indigo-300" />
                </div>
                <div class="min-w-0 flex-1">
                  <h4 class="text-sm font-semibold text-white">
                    {{ t('knowledge.overview.starfield.title') }}
                  </h4>
                </div>
                <button
                  type="button"
                  class="inline-flex shrink-0 items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/70 transition-colors hover:bg-white/15 hover:text-white focus-visible:outline-2 focus-visible:outline-indigo-400"
                  :aria-label="t('knowledge.overview.expand')"
                  @click="starfieldOpen = true"
                >
                  {{ t('knowledge.overview.expand') }}
                  <span class="icon-[lucide--maximize-2] text-[13px]" />
                </button>
              </header>
              <div class="relative h-64">
                <KnowledgeStarfield3D
                  v-if="capsReady && !starfieldOpen"
                  :nodes="starNodes"
                  :links="starLinks"
                  :auto-rotate="true"
                  @open="onStarOpen"
                />
                <div v-else-if="capsLoading" class="flex h-full items-center justify-center text-sm text-white/50">
                  <span class="icon-[lucide--loader-circle] mr-2 animate-spin text-indigo-300" />
                  {{ t('knowledge.overview.panorama.loading') }}
                </div>
                <div v-else-if="!capsReady" class="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
                  <span class="icon-[lucide--orbit] text-2xl text-white/25" />
                  <p class="text-xs text-white/45">
                    {{ t('knowledge.overview.panorama.empty') }}
                  </p>
                </div>
              </div>
            </div>

            <!-- 知识词云（小卡，点击展开大卡） -->
            <div
              role="button"
              tabindex="0"
              :aria-label="t('knowledge.overview.cloud.title')"
              class="group flex cursor-pointer flex-col overflow-hidden rounded-xl border border-border bg-card transition-colors duration-200 hover:border-primary/35 focus-visible:outline-2 focus-visible:outline-primary lg:col-span-2"
              @click="cloudOpen = true"
              @keydown.enter="cloudOpen = true"
              @keydown.space.prevent="cloudOpen = true"
            >
              <header class="flex items-start gap-3 px-4 py-3">
                <div class="stat-icon stat-icon-violet h-9 w-9 shrink-0">
                  <span class="icon-[lucide--cloud] text-base" />
                </div>
                <div class="min-w-0 flex-1">
                  <h4 class="text-sm font-semibold">
                    {{ t('knowledge.overview.cloud.title') }}
                  </h4>
                  <p class="truncate text-xs text-muted-foreground">
                    {{ t('knowledge.overview.cloud.subtitle') }}
                  </p>
                </div>
                <span class="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary">
                  {{ t('knowledge.overview.expand') }}
                  <span class="icon-[lucide--maximize-2] text-[13px]" />
                </span>
              </header>
              <div class="relative h-64 overflow-hidden px-2 pb-2">
                <KnowledgeWordCloud
                  v-if="capsReady && cloudTerms.length"
                  :terms="cloudTerms"
                  :max="120"
                  :min-size="9"
                  :max-size="24"
                  class="pointer-events-none h-full w-full"
                />
                <div v-else-if="capsLoading" class="flex h-full items-center justify-center text-sm text-muted-foreground">
                  <span class="icon-[lucide--loader-circle] mr-2 animate-spin text-primary" />
                  {{ t('knowledge.overview.panorama.loading') }}
                </div>
                <div v-else class="flex h-full flex-col items-center justify-center gap-1 px-6 text-center">
                  <span class="icon-[lucide--cloud] text-2xl text-muted-foreground/30" />
                  <p class="text-xs text-muted-foreground">
                    {{ t('knowledge.overview.panorama.empty') }}
                  </p>
                </div>
              </div>
              <footer class="flex items-center gap-2 border-t border-border/60 px-4 py-2.5 text-[11px] text-muted-foreground/80">
                <span class="icon-[lucide--mouse-pointer-click] text-muted-foreground/50" />
                {{ t('knowledge.overview.cloud.tip') }}
              </footer>
            </div>
          </div>
        </section>

        <!-- 运行状态：双环仪表 + 状态明细 -->
        <section class="card p-5">
          <div class="mb-4 flex items-center gap-2.5">
            <span class="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <span class="icon-[lucide--activity] text-[13px]" />
            </span>
            <h3 class="text-sm font-semibold tracking-wide">
              {{ t('knowledge.overview.health.title') }}
            </h3>
            <span class="ml-auto inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {{ statusBreakdown[0].pct === 100 ? t('knowledge.overview.health.healthy') : t('knowledge.overview.health.running') }}
            </span>
          </div>

          <div class="grid items-center gap-5 sm:grid-cols-[auto_auto_1fr]">
            <!-- 环：索引完成率 -->
            <div class="flex items-center gap-3">
              <div class="relative h-[88px] w-[88px] shrink-0">
                <svg viewBox="0 0 36 36" class="h-[88px] w-[88px] -rotate-90">
                  <circle cx="18" cy="18" r="15.915" fill="none" class="stroke-muted" stroke-width="3.2" />
                  <circle
                    cx="18" cy="18" r="15.915" fill="none"
                    class="stroke-blue-500 transition-all duration-700"
                    stroke-width="3.2" stroke-linecap="round"
                    :stroke-dasharray="`${indexedPct} ${100 - indexedPct}`"
                  />
                </svg>
                <div class="absolute inset-0 flex flex-col items-center justify-center">
                  <span class="text-lg font-bold tabular-nums">{{ indexedPct }}%</span>
                </div>
              </div>
              <div class="text-xs">
                <p class="font-medium">
                  {{ t('knowledge.overview.coverage.indexed') }}
                </p>
                <p class="mt-0.5 text-muted-foreground tabular-nums">
                  {{ indexedRepos }}/{{ totalRepos }}
                </p>
              </div>
            </div>

            <!-- 环：能力树覆盖 -->
            <div class="flex items-center gap-3">
              <div class="relative h-[88px] w-[88px] shrink-0">
                <svg viewBox="0 0 36 36" class="h-[88px] w-[88px] -rotate-90">
                  <circle cx="18" cy="18" r="15.915" fill="none" class="stroke-muted" stroke-width="3.2" />
                  <circle
                    cx="18" cy="18" r="15.915" fill="none"
                    class="stroke-primary transition-all duration-700"
                    stroke-width="3.2" stroke-linecap="round"
                    :stroke-dasharray="`${coveragePct} ${100 - coveragePct}`"
                  />
                </svg>
                <div class="absolute inset-0 flex flex-col items-center justify-center">
                  <span class="text-lg font-bold tabular-nums">{{ coveragePct }}%</span>
                </div>
              </div>
              <div class="text-xs">
                <p class="font-medium">
                  {{ t('knowledge.overview.coverage.ring') }}
                </p>
                <p class="mt-0.5 text-muted-foreground tabular-nums">
                  {{ treedRepos }}/{{ totalRepos }}
                </p>
              </div>
            </div>

            <!-- 状态明细网格 -->
            <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              <div
                v-for="seg in statusBreakdown"
                :key="seg.status"
                class="rounded-xl border border-border/60 bg-muted/30 px-3 py-2"
              >
                <div class="flex items-center gap-1.5">
                  <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="seg.meta.dot" />
                  <span class="truncate text-[11px] text-muted-foreground">{{ seg.meta.label }}</span>
                </div>
                <p class="mt-0.5 text-base font-bold tabular-nums leading-none">
                  {{ seg.count }}
                </p>
              </div>
              <div class="rounded-xl border border-border/60 bg-muted/30 px-3 py-2">
                <div class="flex items-center gap-1.5">
                  <span class="icon-[lucide--boxes] text-[12px] text-violet-500" />
                  <span class="truncate text-[11px] text-muted-foreground">{{ t('knowledge.overview.coverage.monorepo') }}</span>
                </div>
                <p class="mt-0.5 text-base font-bold tabular-nums leading-none">
                  {{ monorepoCount }}
                </p>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- 交付文档 / 外部依赖（按类型计数 + 入口 + 区块内即时搜索）——独立于仓库存在性，靠自身 depLoading/depEmpty 控制 -->
      <section class="card p-5" data-testid="knowledge-deps-section">
        <div class="mb-4 flex items-center gap-2.5">
          <span class="flex h-6 w-6 items-center justify-center rounded-md bg-sky-500/10 text-sky-600 dark:text-sky-400">
            <span class="icon-[lucide--package] text-[13px]" />
          </span>
          <h3 class="text-sm font-semibold tracking-wide">
            {{ t('knowledge.overview.deps.title') }}
          </h3>
          <span class="h-3.5 w-px bg-border" />
          <span class="text-xs text-muted-foreground">{{ t('knowledge.overview.deps.hint') }}</span>
        </div>

        <!-- 加载骨架 -->
        <div v-if="depLoading" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Skeleton v-for="n in 4" :key="n" class="h-[76px] w-full rounded-2xl" />
        </div>

        <!-- 优雅空态：指向作战室「外部依赖」维护入口，不渲染空网格 -->
        <CompactEmptyState
          v-else-if="depEmpty"
          icon="lucide--package"
          :title="t('knowledge.overview.deps.empty.title')"
          :description="t('knowledge.overview.deps.empty.body')"
        />

        <template v-else>
          <!-- 类型计数磁贴（点某类型进搜索预筛） -->
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <button
              v-for="ty in depTypes"
              :key="ty.type_key"
              type="button"
              class="group relative cursor-pointer overflow-hidden rounded-xl border border-border bg-card p-4 text-left transition-colors duration-200 hover:border-primary/35"
              @click="goToDepType(ty.type_key)"
            >
              <div class="flex items-center gap-3.5">
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted/60">
                  <FeishuSheetLogo v-if="ty.carrier === 'feishu_bitable'" class="size-5" />
                  <FeishuLogo v-else-if="ty.carrier === 'feishu_doc'" class="size-5" />
                  <span v-else class="text-lg" :class="[`icon-[${depCarrier(ty.carrier).icon}]`, depCarrier(ty.carrier).color]" />
                </div>
                <div class="min-w-0">
                  <p class="text-xl font-bold leading-none tabular-nums">
                    {{ ty.count }}
                  </p>
                  <p class="mt-1.5 truncate text-xs text-muted-foreground transition-colors group-hover:text-primary">
                    {{ depTypeLabel(ty.type_key, ty.type_name) }}
                  </p>
                </div>
                <span class="icon-[lucide--arrow-up-right] ml-auto shrink-0 text-sm text-muted-foreground/0 transition-colors group-hover:text-primary" />
              </div>
              <span class="absolute inset-x-0 bottom-0 h-[3px] origin-left scale-x-[0.35] bg-primary transition-transform duration-300 group-hover:scale-x-100" />
            </button>
          </div>

          <!-- 区块内即时搜索（客户端过滤已加载条目）+ 条目列表 -->
          <div class="mt-4">
            <div class="relative">
              <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground" />
              <Input
                v-model="depSearch"
                :placeholder="t('knowledge.overview.deps.searchPlaceholder')"
                class="pl-9"
              />
            </div>
            <ul class="mt-3 divide-y divide-border/60">
              <li v-for="item in filteredDepItems" :key="item.artifact_id">
                <div
                  class="group flex w-full items-center gap-2.5 rounded-lg px-1.5 py-2.5 transition-colors hover:bg-muted/40"
                >
                  <!-- 载体图标：飞书文档/表格用各自 logo，其余用品牌色语义图标 -->
                  <FeishuSheetLogo v-if="item.carrier === 'feishu_bitable'" class="size-4 shrink-0" />
                  <FeishuLogo v-else-if="item.carrier === 'feishu_doc'" class="size-4 shrink-0" />
                  <span v-else class="shrink-0 text-base" :class="[`icon-[${depCarrier(item.carrier).icon}]`, depCarrier(item.carrier).color]" />
                  <!-- 类型标签（中文、彩色，置于标题前） -->
                  <span
                    class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :class="depTypeColor(item.type_key, item.type_name)"
                  >{{ depTypeLabel(item.type_key, item.type_name) }}</span>
                  <!-- 标题（点击：markdown 内联预览 / 其余新窗口打开） -->
                  <button
                    type="button"
                    class="min-w-0 flex-1 truncate text-left text-sm transition-colors group-hover:text-primary"
                    @click="openDepItem(item)"
                  >
                    {{ item.title }}
                  </button>
                  <span class="hidden shrink-0 items-center gap-1 text-[11px] text-muted-foreground sm:inline-flex">
                    <span class="icon-[lucide--folder] text-[11px]" />
                    <span class="max-w-[8rem] truncate">{{ item.project_name }}</span>
                  </span>
                  <!-- 操作：markdown 内联预览 / 有链接则新窗口打开 -->
                  <button
                    v-if="item.carrier === 'markdown'"
                    type="button"
                    class="shrink-0 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    :title="t('projects.artifacts.view')"
                    @click="openInlinePreview(item)"
                  >
                    <span class="icon-[lucide--eye] text-[13px]" />
                  </button>
                  <a
                    v-else-if="item.url"
                    :href="item.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="shrink-0 inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    :title="t('projects.artifacts.openExternal')"
                  >
                    <span class="icon-[lucide--external-link] text-[13px]" />
                  </a>
                </div>
              </li>
              <li v-if="!filteredDepItems.length" class="py-4 text-center text-xs text-muted-foreground">
                {{ t('knowledge.overview.deps.noMatch') }}
              </li>
            </ul>
            <!-- 分页：页码写入 URL（?dep_page=），仅按需加载当前页 -->
            <div v-if="depTotal > DEP_PAGE_SIZE" class="mt-3 flex items-center justify-between gap-2">
              <span class="text-[11px] text-muted-foreground tabular-nums">
                {{ t('knowledge.overview.deps.totalCount', { n: depTotal }) }}
              </span>
              <Pagination
                :page="depPage"
                :total="depTotal"
                :items-per-page="DEP_PAGE_SIZE"
                :sibling-count="1"
                show-edges
                @update:page="setDepPage"
              />
            </div>
          </div>
        </template>
      </section>

      <!-- 知识结构：业务域排行 + 分面透视 -->
      <div v-if="domainHighlights.length || activeFacet" class="grid gap-4 lg:grid-cols-2">
        <!-- 业务域排行（条形榜） -->
        <section v-if="domainHighlights.length" class="card flex flex-col p-5">
          <div class="mb-4 flex items-center gap-2.5">
            <span class="flex h-6 w-6 items-center justify-center rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <span class="icon-[lucide--trophy] text-[13px]" />
            </span>
            <h3 class="text-sm font-semibold tracking-wide">
              {{ t('knowledge.overview.domains.title') }}
            </h3>
            <span class="h-3.5 w-px bg-border" />
            <span class="text-xs text-muted-foreground">{{ t('knowledge.overview.domains.hint') }}</span>
            <button
              class="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-primary"
              @click="emit('navigate', 'tree')"
            >
              {{ t('knowledge.overview.domains.viewAll') }}
              <span class="icon-[lucide--chevron-right]" />
            </button>
          </div>
          <ul class="flex flex-1 flex-col gap-0.5">
            <li v-for="(item, i) in domainHighlights" :key="item.node.id">
              <button
                class="group flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-muted/50"
                @click="emit('navigate', 'tree')"
              >
                <span
                  class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold tabular-nums"
                  :class="i < 3 ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'"
                >{{ i + 1 }}</span>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="truncate text-sm font-medium transition-colors group-hover:text-primary">{{ item.node.title }}</span>
                    <span v-if="item.node.children.length" class="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {{ item.node.children.length }} {{ t('knowledge.overview.domains.subUnit') }}
                    </span>
                  </div>
                  <p v-if="item.node.summary" class="mt-0.5 truncate text-[11px] text-muted-foreground">
                    {{ item.node.summary }}
                  </p>
                  <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      class="h-full rounded-full bg-gradient-to-r from-primary/60 to-primary transition-all duration-500"
                      :style="{ width: `${Math.round((item.repos / domainMaxRepos) * 100)}%` }"
                    />
                  </div>
                </div>
                <span class="shrink-0 text-sm font-semibold tabular-nums">
                  {{ item.repos }}<span class="ml-0.5 text-[11px] font-normal text-muted-foreground">{{ t('knowledge.overview.domains.repoUnit') }}</span>
                </span>
              </button>
            </li>
          </ul>
        </section>

        <!-- 分面透视（维度切换 + 分布） -->
        <section v-if="activeFacet" class="card flex flex-col p-5">
          <div class="mb-3 flex items-center gap-2.5">
            <span class="flex h-6 w-6 items-center justify-center rounded-md bg-violet-500/10 text-violet-600 dark:text-violet-400">
              <span class="icon-[lucide--sliders-horizontal] text-[13px]" />
            </span>
            <h3 class="text-sm font-semibold tracking-wide">
              {{ t('knowledge.overview.facets.title') }}
            </h3>
            <span class="h-3.5 w-px bg-border" />
            <span class="text-xs text-muted-foreground">{{ t('knowledge.overview.facets.hint') }}</span>
          </div>
          <!-- 维度切换 -->
          <div class="mb-4 flex flex-wrap gap-1.5">
            <button
              v-for="dim in facetDimensions"
              :key="dim.dim"
              class="rounded-full px-2.5 py-1 text-xs font-medium transition-colors"
              :class="activeFacet.dim === dim.dim
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'bg-muted text-muted-foreground hover:bg-muted/70 hover:text-foreground'"
              @click="selectedFacetDim = dim.dim"
            >
              {{ dim.dim }}
            </button>
          </div>
          <!-- 当前维度分布 -->
          <div class="flex-1 space-y-2.5 overflow-y-auto pr-1" style="max-height: 300px">
            <div v-for="v in activeFacet.values" :key="v.value">
              <div class="mb-1 flex items-center justify-between gap-2 text-xs">
                <span class="truncate text-foreground/80">{{ v.value }}</span>
                <span class="shrink-0 tabular-nums text-muted-foreground">{{ v.count }} · {{ v.pct }}%</span>
              </div>
              <div class="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary/80 transition-all duration-500"
                  :style="{ width: `${Math.round((v.count / facetMax) * 100)}%` }"
                />
              </div>
            </div>
          </div>
        </section>
      </div>
    </template>

    <!-- ============ 星图详情弹窗（接近全屏的大图，GSAP 展开过渡） ============ -->
    <Dialog v-model:open="starfieldOpen">
      <DialogContent class="flex h-[90vh] w-[96vw] max-w-[1400px] flex-col overflow-hidden border-indigo-500/20 bg-[#070713] p-0 text-white sm:max-w-[1400px]">
        <div ref="starModalEl" class="flex min-h-0 flex-1 flex-col">
          <header class="flex shrink-0 items-start gap-3 px-5 pt-5 pb-3">
            <div data-anim class="shrink-0 rounded-xl bg-indigo-500/15 p-2 ring-1 ring-inset ring-indigo-400/20">
              <span class="icon-[lucide--orbit] text-lg text-indigo-300" />
            </div>
            <div data-anim class="min-w-0 flex-1">
              <DialogTitle class="text-base font-semibold text-white">
                {{ t('knowledge.overview.starfield.title') }}
              </DialogTitle>
              <DialogDescription class="sr-only">
                {{ t('knowledge.overview.panorama.title') }}
              </DialogDescription>
            </div>
            <div data-anim class="mr-8 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/55">
              <span class="inline-flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#818cf8" /> {{ t('knowledge.overview.starfield.legendRepo') }}</span>
              <span class="inline-flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#c084fc" /> {{ t('knowledge.overview.starfield.legendSubApp') }}</span>
              <span class="inline-flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#2dd4bf" /> {{ t('knowledge.overview.starfield.legendModule') }}</span>
              <span class="inline-flex items-center gap-1"><span class="h-2 w-2 rounded-full" style="background:#fbbf24" /> {{ t('knowledge.overview.starfield.legendCapability') }}</span>
            </div>
          </header>
          <div class="relative min-h-0 flex-1">
            <div v-if="starfieldOpen && capsReady && starfieldMount" ref="starStageEl" class="h-full w-full">
              <KnowledgeStarfield3D
                :nodes="starNodes"
                :links="starLinks"
                :auto-rotate="true"
                @open="onStarOpen"
              />
            </div>
            <!-- 数据已就绪、3D 尚未挂载：编织星图的过渡动效 -->
            <div v-else-if="starfieldOpen && capsReady" class="absolute inset-0 flex flex-col items-center justify-center gap-4">
              <div class="star-forming">
                <span class="icon-[lucide--orbit] text-2xl text-indigo-300" />
              </div>
              <p class="text-xs text-white/45">
                {{ t('knowledge.overview.panorama.weaving') }}
              </p>
            </div>
            <!-- 确实无数据 -->
            <div v-else-if="starfieldOpen && !capsReady" class="flex h-full items-center justify-center text-sm text-white/50">
              {{ t('knowledge.overview.panorama.empty') }}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- ============ 词云详情弹窗 ============ -->
    <Dialog v-model:open="cloudOpen">
      <DialogContent class="w-[94vw] max-w-4xl">
        <header class="flex items-start gap-3">
          <div class="stat-icon stat-icon-violet h-9 w-9 shrink-0">
            <span class="icon-[lucide--cloud] text-base" />
          </div>
          <div class="min-w-0 flex-1">
            <DialogTitle class="text-base font-semibold">
              {{ t('knowledge.overview.cloud.title') }}
            </DialogTitle>
            <DialogDescription class="text-xs text-muted-foreground">
              {{ t('knowledge.overview.cloud.hint') }}
            </DialogDescription>
          </div>
        </header>
        <div class="h-[72vh]">
          <KnowledgeWordCloud
            :terms="cloudTerms"
            :max="200"
            :min-size="16"
            :max-size="76"
            @pick="onCloudPick"
          />
        </div>
      </DialogContent>
    </Dialog>

    <!-- ============ 交付文档 markdown 内联预览 ============ -->
    <Dialog v-model:open="previewOpen">
      <DialogContent class="flex h-[88vh] w-[92vw] max-w-5xl flex-col">
        <DialogTitle class="text-base font-semibold">
          {{ previewTitle }}
        </DialogTitle>
        <DialogDescription class="sr-only">
          {{ t('projects.artifacts.viewDesc') }}
        </DialogDescription>
        <div class="min-h-0 flex-1 overflow-auto">
          <div v-if="previewLoading" class="py-8 text-center text-sm text-muted-foreground">
            {{ t('projects.loading') }}
          </div>
          <template v-else-if="previewData">
            <p v-if="previewData.error" class="text-sm text-destructive">
              {{ previewData.error }}
            </p>
            <MarkdownRenderer
              v-else-if="previewData.render_type === 'markdown'"
              :content="previewData.content || ''"
            />
            <pre
              v-else-if="previewData.render_type === 'text'"
              class="whitespace-pre-wrap break-words rounded-lg bg-muted/40 p-3 text-xs"
            >{{ previewData.content }}</pre>
            <a
              v-else-if="previewData.url"
              :href="previewData.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm text-primary underline break-all"
            >{{ previewData.url }}</a>
            <p v-else class="text-sm text-muted-foreground">
              {{ t('projects.artifacts.unsupported') }}
            </p>
          </template>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

<style scoped>
/* 「编织星图」过渡：自转的发光环 + 脉冲光晕 */
.star-forming {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 76px;
  height: 76px;
  border-radius: 9999px;
}

.star-forming::before,
.star-forming::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 9999px;
  border: 2px solid transparent;
}

.star-forming::before {
  border-top-color: rgba(129, 140, 248, 0.9);
  border-right-color: rgba(129, 140, 248, 0.35);
  animation: star-spin 1.1s linear infinite;
}

.star-forming::after {
  inset: 10px;
  border-bottom-color: rgba(45, 212, 191, 0.85);
  border-left-color: rgba(45, 212, 191, 0.3);
  animation: star-spin 1.6s linear infinite reverse;
}

@keyframes star-spin {
  to {
    transform: rotate(360deg);
  }
}

.star-forming > span {
  animation: star-pulse 1.4s ease-in-out infinite;
}

@keyframes star-pulse {
  0%,
  100% {
    opacity: 0.55;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1.08);
  }
}

@media (prefers-reduced-motion: reduce) {
  .star-forming::before,
  .star-forming::after,
  .star-forming > span {
    animation: none;
  }
}
</style>
