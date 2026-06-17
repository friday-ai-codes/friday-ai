<script setup lang="ts">
import type { ProvenanceLinks } from '~/api/knowledge'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { knowledgeApi } from '~/api'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import BatchIngestPanel from '~/components/knowledge/BatchIngestPanel.vue'
import EntityDetailToolbar from '~/components/knowledge/EntityDetailToolbar.vue'
import EntityKindBadge from '~/components/knowledge/EntityKindBadge.vue'
import ProvenanceLinkButton from '~/components/knowledge/ProvenanceLinkButton.vue'
import ReleaseSyncPanel from '~/components/knowledge/ReleaseSyncPanel.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Skeleton } from '~/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'

const { t } = useI18n()
const queryClient = useQueryClient()

const activeTab = ref<'search' | 'ingest' | 'release'>('search')
const showFilters = ref(false)

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
const hasSearched = computed(() => submittedQuery.value.length > 0)
</script>

<template>
  <PageContainer show-background>
    <!-- 页头（与其他页面统一：渐变图标 + 标题 + 描述） -->
    <PageHeader
      icon="lucide--book-open"
      icon-gradient="from-primary/20 to-primary/10"
      icon-color="text-primary"
      :title="t('knowledge.pageTitle')"
      :description="t('knowledge.pageDescription')"
    />

    <Tabs v-model="activeTab" class="mt-5">
      <TabsList>
        <TabsTrigger value="search">
          <span class="icon-[lucide--search]" />
          {{ t('knowledge.tabs.search') }}
        </TabsTrigger>
        <TabsTrigger value="ingest">
          <span class="icon-[lucide--download]" />
          {{ t('knowledge.tabs.ingest') }}
        </TabsTrigger>
        <TabsTrigger value="release">
          <span class="icon-[lucide--cloud-download]" />
          {{ t('knowledge.tabs.release') }}
        </TabsTrigger>
      </TabsList>

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

        <div v-else-if="!results.length" class="flex min-h-[380px] items-center justify-center">
          <CompactEmptyState
            icon="icon-[lucide--file-x]"
            :title="t('knowledge.search.emptyTitle')"
            :description="t('knowledge.search.emptyBody')"
          />
        </div>

        <!-- 结果（双列网格，充分利用横向空间） -->
        <div v-else class="space-y-3" data-testid="knowledge-search-results">
          <p class="text-xs text-muted-foreground">
            {{ t('knowledge.search.resultCount', { count: results.length }) }}
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div
              v-for="item in results"
              :key="`${item.entity_id}-${item.version}`"
              class="group card p-4 space-y-2.5 transition-all duration-200 hover:border-primary/30 hover:shadow-md"
              data-testid="knowledge-search-result"
            >
              <div class="flex items-start gap-2.5">
                <EntityKindBadge :kind="item.kind" class="mt-0.5 shrink-0" />
                <RouterLink
                  :to="`/knowledge/entities/${item.entity_id}`"
                  class="flex-1 min-w-0 inline-flex items-center gap-1 text-sm font-medium leading-snug transition-colors hover:text-primary"
                >
                  <span class="truncate">{{ item.title }}</span>
                  <span class="icon-[lucide--chevron-right] shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </RouterLink>
              </div>
              <div class="flex items-center gap-2 text-xs text-muted-foreground">
                <span class="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 font-mono">
                  <span class="icon-[lucide--gauge] text-[11px]" />
                  {{ t('knowledge.search.scoreLabel') }} {{ item.score.toFixed(3) }}
                </span>
              </div>
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

      <TabsContent value="release" class="mt-5">
        <ReleaseSyncPanel />
      </TabsContent>
    </Tabs>
  </PageContainer>
</template>
