<script setup lang="ts">
import type { ArtifactView } from '~/api/artifacts'
import type { KnowledgeSearchResultItem, ProvenanceLinks } from '~/api/knowledge'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { knowledgeApi } from '~/api'
import { artifactsApi } from '~/api/artifacts'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import { ARTIFACT_BADGE_CLASS } from '~/components/knowledge/artifactDisplay'
import BatchIngestPanel from '~/components/knowledge/BatchIngestPanel.vue'
import BlueprintsTabPanel from '~/components/knowledge/BlueprintsTabPanel.vue'
import DeliveryDocsTree from '~/components/knowledge/DeliveryDocsTree.vue'
import EntityDetailToolbar from '~/components/knowledge/EntityDetailToolbar.vue'
import EntityKindBadge from '~/components/knowledge/EntityKindBadge.vue'
import KnowledgeDashboard from '~/components/knowledge/KnowledgeDashboard.vue'
import KnowledgeTreePanel from '~/components/knowledge/KnowledgeTreePanel.vue'
import ProvenanceLinkButton from '~/components/knowledge/ProvenanceLinkButton.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Skeleton } from '~/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { useErrorHandler } from '~/composables/useErrorHandler'

const { t } = useI18n()
const queryClient = useQueryClient()
const route = useRoute()
const router = useRouter()

type KnowledgeTab = 'overview' | 'tree' | 'ingest' | 'search'
  | 'blueprints'
const TABS: KnowledgeTab[] = ['overview', 'tree', 'ingest', 'search']
// Phase 115 追加点 #1：技术方案 tab。⭐ 用 push 追加而不是改写上面那行 —— 既有行保持
// 逐字不变；下面那个兜底函数在调用时才读 TABS，新 tab 自动被它认可（⛔ 其实现一行未改）。
TABS.push('blueprints')

function normalizeTab(value: unknown): KnowledgeTab {
  return TABS.includes(value as KnowledgeTab) ? (value as KnowledgeTab) : 'overview'
}

// 默认进入「总览」；与路由 ?tab= 双向同步，支持深链。
const activeTab = ref<KnowledgeTab>(normalizeTab(route.query.tab))
const showFilters = ref(false)

watch(() => route.query.tab, (v) => {
  const next = normalizeTab(v)
  if (next !== activeTab.value)
    activeTab.value = next
})

watch(activeTab, (v) => {
  if (route.query.tab !== v)
    router.replace({ query: { ...route.query, tab: v } })
})

// tree Tab 视图切换（代码能力树 | 交付文档），默认代码能力树；与 ?view= 双向同步支持深链。
type TreeView = 'capability' | 'docs'
function normalizeTreeView(value: unknown): TreeView {
  return value === 'docs' ? 'docs' : 'capability'
}
const treeView = ref<TreeView>(normalizeTreeView(route.query.view))

watch(() => route.query.view, (v) => {
  const next = normalizeTreeView(v)
  if (next !== treeView.value)
    treeView.value = next
})

watch(treeView, (v) => {
  if (route.query.view !== v)
    router.replace({ query: { ...route.query, view: v } })
})

// 类型预筛：总览「交付文档」类型磁贴跳搜索 Tab 时带 ?dep_type=<type_key>，此处消费。
// 客户端按结果中的 artifact.type_key 过滤，并以可清除的筛选 chip 反映当前约束。
function readDepType(v: unknown): string {
  return typeof v === 'string' && v.length > 0 ? v : ''
}
const depTypeFilter = ref(readDepType(route.query.dep_type))
watch(() => route.query.dep_type, (v) => {
  depTypeFilter.value = readDepType(v)
})

// 类型名解析：复用总览聚合缓存（同 queryKey 去重），仅在存在类型预筛时启用。
const overviewQuery = useQuery({
  queryKey: ['knowledge', 'artifact-overview'],
  queryFn: () => knowledgeApi.getArtifactOverview(),
  enabled: computed(() => depTypeFilter.value.length > 0),
  staleTime: 60_000,
})
const depTypeName = computed(() => {
  const key = depTypeFilter.value
  if (!key)
    return ''
  const match = overviewQuery.data.value?.types.find(ty => ty.type_key === key)
  return match?.type_name ?? key
})

function clearDepType() {
  depTypeFilter.value = ''
  const { dep_type: _omit, ...rest } = route.query
  router.replace({ query: rest })
}

// 输入框当前值与「已提交」查询词分离：仅点击搜索 / 回车时提交，避免输入即触发请求。
const queryInput = ref('')
const submittedQuery = ref('')
const asOfLocal = ref('')
const asOfIso = ref<string | null>(null)
const includeSuperseded = ref(false)

function localToIso(local: string): string | null {
  if (!local)
    return null
  const dt = new Date(local)
  if (Number.isNaN(dt.getTime()))
    return null
  return dt.toISOString()
}

function hasProvenance(provenance: ProvenanceLinks): boolean {
  return Boolean(provenance.feishu_url || provenance.mr_url || provenance.session_link)
}

function onSearch() {
  submittedQuery.value = queryInput.value.trim()
  asOfIso.value = localToIso(asOfLocal.value)
  queryClient.invalidateQueries({ queryKey: ['knowledge', 'search'] })
}

function resetAsOf() {
  asOfLocal.value = ''
  asOfIso.value = null
}

const searchQuery = useQuery({
  queryKey: computed(() => ['knowledge', 'search', submittedQuery.value, asOfIso.value, includeSuperseded.value]),
  queryFn: () => knowledgeApi.searchDeliveryKnowledge({
    q: submittedQuery.value,
    asOf: asOfIso.value,
    includeSuperseded: includeSuperseded.value,
  }),
  enabled: computed(() => submittedQuery.value.length > 0),
  staleTime: 30_000,
})

const results = computed(() => searchQuery.data.value ?? [])
// 类型预筛（?dep_type=）客户端过滤：仅保留命中该类型工件的结果。
const displayResults = computed(() => {
  if (!depTypeFilter.value)
    return results.value
  return results.value.filter(item => item.artifact?.type_key === depTypeFilter.value)
})
const hasSearched = computed(() => submittedQuery.value.length > 0)

// ── 工件命中：类型徽标 + 项目名 + 一键查看（复用 DependenciesSection 弹窗范式）──
const { handleError } = useErrorHandler()

const viewOpen = ref(false)
const viewLoading = ref(false)
const viewData = ref<ArtifactView | null>(null)
const viewTitle = ref('')

function isExternalArtifact(item: KnowledgeSearchResultItem): boolean {
  return item.artifact?.carrier === 'external_link'
}

async function openArtifactView(item: KnowledgeSearchResultItem) {
  if (!item.artifact)
    return
  viewTitle.value = item.title
  viewData.value = null
  viewOpen.value = true
  viewLoading.value = true
  try {
    viewData.value = await artifactsApi.view(item.artifact.project_id, item.artifact.artifact_id)
  }
  catch (e: unknown) {
    handleError(e, t('projects.artifacts.viewFailed'))
    viewOpen.value = false
  }
  finally {
    viewLoading.value = false
  }
}
</script>

<template>
  <PageContainer show-background>
    <!-- 扁平 hero 页头：品牌 teal 色面 + 纯色几何装饰（同心圆环/点阵，无渐变阴影） -->
    <div class="relative overflow-hidden rounded-2xl border border-primary/15 bg-primary/[0.06] px-6 py-6">
      <div class="pointer-events-none absolute -right-12 -top-16 h-48 w-48 rounded-full border-[12px] border-primary/10" aria-hidden="true" />
      <div class="pointer-events-none absolute -bottom-12 right-28 h-28 w-28 rounded-full border-8 border-primary/[0.07]" aria-hidden="true" />
      <div class="pointer-events-none absolute right-7 top-6 hidden grid-cols-6 gap-2 sm:grid" aria-hidden="true">
        <span v-for="n in 18" :key="n" class="h-1 w-1 rounded-full bg-primary/25" />
      </div>
      <div class="relative flex items-center gap-4">
        <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <span class="icon-[lucide--book-open] text-2xl" />
        </div>
        <div class="min-w-0">
          <h1 class="text-2xl font-bold tracking-tight">
            {{ t('knowledge.pageTitle') }}
          </h1>
          <p class="mt-1 text-sm text-muted-foreground">
            {{ t('knowledge.pageDescription') }}
          </p>
        </div>
      </div>
    </div>

    <Tabs v-model="activeTab" class="mt-5">
      <TabsList class="h-10 gap-1 rounded-xl bg-muted/70 p-1">
        <TabsTrigger
          v-for="tab in ([
            { value: 'overview', icon: 'icon-[lucide--layout-dashboard]' },
            { value: 'tree', icon: 'icon-[lucide--folder-tree]' },
            { value: 'ingest', icon: 'icon-[lucide--download]' },
            { value: 'search', icon: 'icon-[lucide--search]' },
            { value: 'blueprints', icon: 'icon-[lucide--file-text]' },
          ] as const)"
          :key="tab.value"
          :value="tab.value"
          class="cursor-pointer rounded-lg px-3.5 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-none dark:data-[state=active]:bg-primary dark:data-[state=active]:text-primary-foreground"
        >
          <span :class="tab.icon" />
          {{ t(`knowledge.tabs.${tab.value}`) }}
        </TabsTrigger>
      </TabsList>

      <!-- 技术方案（Phase 115 追加点 #1，纯追加：tab 兜底函数、?tab= 同步与既有四个 tab 一行未改） -->
      <TabsContent value="blueprints" class="mt-5">
        <BlueprintsTabPanel />
      </TabsContent>

      <TabsContent value="overview" class="mt-5">
        <KnowledgeDashboard @navigate="activeTab = $event" />
      </TabsContent>

      <TabsContent value="search" class="mt-5 space-y-5">
        <!-- 搜索栏（带前置图标，突出主操作） -->
        <div class="space-y-2">
          <div class="flex gap-2 max-w-3xl">
            <div class="relative flex-1">
              <span class="icon-[lucide--search] absolute left-3.5 top-1/2 -translate-y-1/2 text-base text-muted-foreground pointer-events-none" />
              <Input
                v-model="queryInput"
                class="h-11 pl-10 text-sm"
                :placeholder="t('knowledge.search.placeholder')"
                data-testid="knowledge-search-input"
                @keydown.enter="onSearch"
              />
            </div>
            <Button class="h-11 px-5" data-testid="knowledge-search-button" @click="onSearch">
              <span class="icon-[lucide--search] mr-1.5" />
              {{ t('knowledge.search.button') }}
            </Button>
          </div>

          <!-- 类型预筛 chip（来自总览「交付文档」类型磁贴的 ?dep_type=，可一键清除） -->
          <div v-if="depTypeFilter" class="max-w-3xl">
            <span
              class="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 py-1 pl-3 pr-1.5 text-xs font-medium text-primary"
              data-testid="knowledge-dep-type-chip"
            >
              <span class="icon-[lucide--filter] text-[13px]" />
              {{ t('knowledge.search.typeFilterLabel', { name: depTypeName }) }}
              <button
                type="button"
                class="inline-flex h-4 w-4 items-center justify-center rounded-full transition-colors hover:bg-primary/20"
                :aria-label="t('knowledge.search.clearTypeFilter')"
                data-testid="knowledge-dep-type-clear"
                @click="clearDepType"
              >
                <span class="icon-[lucide--x] text-[12px]" />
              </button>
            </span>
          </div>

          <!-- 历史视点折叠（默认收起，避免次要筛选喧宾夺主） -->
          <div class="max-w-3xl">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 -ml-2 text-xs text-muted-foreground transition-colors hover:text-foreground hover:bg-muted/60"
              @click="showFilters = !showFilters"
            >
              <span class="icon-[lucide--sliders-horizontal]" />
              {{ t('knowledge.entity.asOf.label') }}
              <span class="icon-[lucide--chevron-down] transition-transform" :class="{ 'rotate-180': showFilters }" />
            </button>
            <div v-show="showFilters" class="mt-2">
              <EntityDetailToolbar
                v-model:as-of-local="asOfLocal"
                v-model:include-superseded="includeSuperseded"
                @reset="resetAsOf"
              />
            </div>
          </div>
        </div>

        <!-- 加载骨架（网格占位，填满横向空间） -->
        <div v-if="hasSearched && searchQuery.isLoading.value" class="grid gap-3 sm:grid-cols-2">
          <Skeleton v-for="n in 4" :key="n" class="h-28 w-full rounded-2xl" />
        </div>

        <!-- 初始 / 空态：纵向居中填充，避免大片留白 -->
        <div v-else-if="!hasSearched" class="flex min-h-[380px] items-center justify-center">
          <CompactEmptyState
            icon="icon-[lucide--book-open]"
            :title="t('knowledge.search.initialTitle')"
            :description="t('knowledge.search.initialBody')"
          />
        </div>

        <div v-else-if="!displayResults.length" class="flex min-h-[380px] items-center justify-center">
          <CompactEmptyState
            icon="icon-[lucide--file-x]"
            :title="t('knowledge.search.emptyTitle')"
            :description="t('knowledge.search.emptyBody')"
          />
        </div>

        <!-- 结果（双列网格，充分利用横向空间） -->
        <div v-else class="space-y-3" data-testid="knowledge-search-results">
          <p class="text-xs text-muted-foreground">
            {{ t('knowledge.search.resultCount', { count: displayResults.length }) }}
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div
              v-for="item in displayResults"
              :key="`${item.entity_id}-${item.version}`"
              class="group card p-4 space-y-2.5 transition-all duration-200 hover:border-primary/30 hover:shadow-md"
              data-testid="knowledge-search-result"
            >
              <div class="flex items-start gap-2.5">
                <EntityKindBadge :kind="item.kind" class="mt-0.5 shrink-0" />
                <!-- 工件类型徽标（PRD/埋点评审/UI…），仅工件命中时展示 -->
                <Badge
                  v-if="item.artifact"
                  variant="outline"
                  :class="ARTIFACT_BADGE_CLASS"
                  class="mt-0.5 shrink-0"
                  data-testid="artifact-type-badge"
                >
                  {{ item.artifact.type_name }}
                </Badge>
                <RouterLink
                  :to="`/knowledge/entities/${item.entity_id}`"
                  class="flex-1 min-w-0 inline-flex items-center gap-1 text-sm font-medium leading-snug transition-colors hover:text-primary"
                >
                  <span class="truncate">{{ item.title }}</span>
                  <span class="icon-[lucide--chevron-right] shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </RouterLink>
              </div>
              <div class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span class="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 font-mono">
                  <span class="icon-[lucide--gauge] text-[11px]" />
                  {{ t('knowledge.search.scoreLabel') }} {{ item.score.toFixed(3) }}
                </span>
                <!-- 所属项目名（跨项目搜索时分辨归属） -->
                <span
                  v-if="item.artifact"
                  class="inline-flex items-center gap-1"
                  :title="t('knowledge.search.owningProject')"
                >
                  <span class="icon-[lucide--folder] text-[11px]" />
                  <span class="truncate max-w-[10rem]">{{ item.artifact.project_name }}</span>
                </span>
              </div>
              <!-- 一键查看：external_link 新标签打开外链；其余文字载体走查看弹窗 -->
              <a
                v-if="item.artifact && isExternalArtifact(item)"
                :href="item.artifact.url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                data-testid="artifact-open-external"
              >
                <span class="icon-[lucide--external-link] text-[13px]" />
                {{ t('knowledge.search.openExternal') }}
              </a>
              <Button
                v-else-if="item.artifact"
                size="sm"
                variant="outline"
                class="h-7 gap-1 px-2 text-xs"
                data-testid="artifact-view-btn"
                @click="openArtifactView(item)"
              >
                <span class="icon-[lucide--eye] text-[13px]" />
                {{ t('knowledge.search.view') }}
              </Button>
              <ProvenanceLinkButton
                v-if="hasProvenance(item.provenance)"
                :provenance="item.provenance"
                :title="item.title"
              />
            </div>
          </div>
        </div>
      </TabsContent>

      <TabsContent value="ingest" class="mt-5">
        <div class="max-w-3xl">
          <BatchIngestPanel />
        </div>
      </TabsContent>

      <TabsContent value="tree" class="mt-5 space-y-4">
        <!-- 视图切换：代码能力树（PageIndex，默认）｜交付文档（并行树）。样式复用工具栏 segmented control 令牌 -->
        <div class="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-muted/40 p-1 w-fit">
          <button
            type="button"
            class="rounded-md px-3 py-1 text-xs transition-colors"
            :class="treeView === 'capability' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'"
            data-testid="tree-view-capability"
            @click="treeView = 'capability'"
          >
            {{ t('knowledge.tree.viewSwitch.capability') }}
          </button>
          <button
            type="button"
            class="rounded-md px-3 py-1 text-xs transition-colors"
            :class="treeView === 'docs' ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'"
            data-testid="tree-view-docs"
            @click="treeView = 'docs'"
          >
            {{ t('knowledge.tree.viewSwitch.docs') }}
          </button>
        </div>

        <KnowledgeTreePanel v-if="treeView === 'capability'" />
        <DeliveryDocsTree v-else />
      </TabsContent>
    </Tabs>

    <!-- 工件在线查看弹窗（复用 DependenciesSection 范式） -->
    <Dialog v-model:open="viewOpen">
      <DialogScrollContent class="w-[92vw] max-w-5xl">
        <DialogHeader>
          <DialogTitle>{{ viewTitle }}</DialogTitle>
          <DialogDescription>{{ t('projects.artifacts.viewDesc') }}</DialogDescription>
        </DialogHeader>
        <div class="mt-2">
          <div v-if="viewLoading" class="text-sm text-muted-foreground py-6 text-center">
            {{ t('knowledge.search.loading') }}
          </div>
          <template v-else-if="viewData">
            <p v-if="viewData.error" class="text-sm text-destructive">
              {{ viewData.error }}
            </p>
            <a
              v-else-if="viewData.render_type === 'link'"
              :href="viewData.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm text-primary underline break-all"
            >
              {{ viewData.url }}
            </a>
            <div
              v-else-if="viewData.render_type === 'markdown'"
              class="max-h-[72vh] overflow-auto"
            >
              <MarkdownRenderer :content="viewData.content || ''" />
            </div>
            <pre
              v-else-if="viewData.render_type === 'text'"
              class="text-xs bg-muted/50 rounded-lg p-3 max-h-[72vh] overflow-auto whitespace-pre-wrap"
            >{{ viewData.content }}</pre>
            <div v-else-if="viewData.render_type === 'records'" class="text-xs space-y-1 max-h-[72vh] overflow-auto">
              <p class="text-muted-foreground">
                {{ t('projects.artifacts.recordCount', { n: viewData.records?.length ?? 0 }) }}
              </p>
              <pre class="bg-muted/50 rounded-lg p-3 overflow-auto">{{ JSON.stringify(viewData.records, null, 2) }}</pre>
            </div>
            <p v-else class="text-sm text-muted-foreground">
              {{ t('projects.artifacts.unsupported') }}
            </p>
          </template>
        </div>
      </DialogScrollContent>
    </Dialog>
  </PageContainer>
</template>
