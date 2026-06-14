<script setup lang="ts">
import type { ProvenanceLinks } from '~/api/knowledge'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { knowledgeApi } from '~/api'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import EntityDetailToolbar from '~/components/knowledge/EntityDetailToolbar.vue'
import EntityKindBadge from '~/components/knowledge/EntityKindBadge.vue'
import ProvenanceLinkButton from '~/components/knowledge/ProvenanceLinkButton.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Skeleton } from '~/components/ui/skeleton'

const { t } = useI18n()
const queryClient = useQueryClient()

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
  <PageContainer>
    <div class="space-y-4 max-w-3xl">
      <h1 class="text-xl font-semibold">
        {{ t('knowledge.search.title') }}
      </h1>

      <div class="flex gap-2">
        <Input
          v-model="queryInput"
          :placeholder="t('knowledge.search.placeholder')"
          data-testid="knowledge-search-input"
          @keydown.enter="onSearch"
        />
        <Button data-testid="knowledge-search-button" @click="onSearch">
          {{ t('knowledge.search.button') }}
        </Button>
      </div>

      <EntityDetailToolbar
        v-model:as-of-local="asOfLocal"
        v-model:include-superseded="includeSuperseded"
        @reset="resetAsOf"
      />

      <Skeleton v-if="hasSearched && searchQuery.isLoading.value" class="h-40 w-full" />

      <CompactEmptyState
        v-else-if="!hasSearched"
        icon="icon-[lucide--search]"
        :title="t('knowledge.search.initialTitle')"
        :description="t('knowledge.search.initialBody')"
      />

      <CompactEmptyState
        v-else-if="!results.length"
        icon="icon-[lucide--file-x]"
        :title="t('knowledge.search.emptyTitle')"
        :description="t('knowledge.search.emptyBody')"
      />

      <div v-else class="space-y-3" data-testid="knowledge-search-results">
        <p class="text-xs text-muted-foreground">
          {{ t('knowledge.search.resultCount', { count: results.length }) }}
        </p>
        <div
          v-for="item in results"
          :key="`${item.entity_id}-${item.version}`"
          class="card p-4 space-y-2 hover:bg-muted/30"
          data-testid="knowledge-search-result"
        >
          <div class="flex items-center gap-2">
            <EntityKindBadge :kind="item.kind" />
            <RouterLink
              :to="`/knowledge/entities/${item.entity_id}`"
              class="text-sm font-medium hover:text-primary"
            >
              {{ item.title }}
            </RouterLink>
          </div>
          <p class="text-xs text-muted-foreground">
            {{ t('knowledge.search.scoreLabel') }}: {{ item.score.toFixed(3) }}
          </p>
          <ProvenanceLinkButton
            v-if="hasProvenance(item.provenance)"
            :provenance="item.provenance"
            :title="item.title"
          />
        </div>
      </div>
    </div>
  </PageContainer>
</template>
