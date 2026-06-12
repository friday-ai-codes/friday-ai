<script setup lang="ts">
import type { NavSection } from '~/components/layout/AnchorNavLayout.vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useHead } from '@vueuse/head'
import { useI18n } from 'vue-i18n'
import AnchorNavLayout from '~/components/layout/AnchorNavLayout.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Skeleton } from '~/components/ui/skeleton'
import EntityDetailToolbar from '~/components/knowledge/EntityDetailToolbar.vue'
import EntityMetadataCard from '~/components/knowledge/EntityMetadataCard.vue'
import EntityRelationTree from '~/components/knowledge/EntityRelationTree.vue'
import EntityVersionTimeline from '~/components/knowledge/EntityVersionTimeline.vue'
import { knowledgeApi } from '~/api'
import { ApiError } from '~/api/client'

const route = useRoute('/knowledge/entities/[id]')
const queryClient = useQueryClient()
const { t } = useI18n()

const entityId = computed(() => String(route.params.id))
const asOfIso = ref<string | null>(null)
const asOfLocal = ref('')
const includeSuperseded = ref(false)

function localToIso(local: string): string | null {
  if (!local)
    return null
  const dt = new Date(local)
  if (Number.isNaN(dt.getTime()))
    return null
  return dt.toISOString()
}

watch(asOfLocal, (val) => {
  asOfIso.value = localToIso(val)
  queryClient.invalidateQueries({ queryKey: ['knowledge'] })
})

watch(includeSuperseded, () => {
  queryClient.invalidateQueries({ queryKey: ['knowledge'] })
})

const entityQuery = useQuery({
  queryKey: computed(() => ['knowledge', 'entity', entityId.value, asOfIso.value]),
  queryFn: () => knowledgeApi.getEntity(entityId.value, { asOf: asOfIso.value }),
  staleTime: 30_000,
})

const timelineQuery = useQuery({
  queryKey: computed(() => ['knowledge', 'timeline', entityId.value, asOfIso.value, includeSuperseded.value]),
  queryFn: () => knowledgeApi.getTimeline(entityId.value, {
    asOf: asOfIso.value,
    includeSuperseded: includeSuperseded.value,
  }),
  staleTime: 30_000,
})

const relatedQuery = useQuery({
  queryKey: computed(() => ['knowledge', 'related', entityId.value, asOfIso.value]),
  queryFn: () => knowledgeApi.getRelated(entityId.value, { asOf: asOfIso.value }),
  staleTime: 30_000,
})

const sections = computed<NavSection[]>(() => [
  { id: 'entity-metadata', label: t('knowledge.entity.sections.metadata') },
  { id: 'entity-timeline', label: t('knowledge.entity.sections.timeline') },
  { id: 'entity-related', label: t('knowledge.entity.sections.related') },
])

useHead({
  title: computed(() => entityQuery.data.value
    ? `${entityQuery.data.value.title} - ${t('knowledge.entity.pageTitle')} - Friday AI`
    : `${t('knowledge.entity.pageTitle')} - Friday AI`),
})

const is404 = computed(() => entityQuery.error.value instanceof ApiError && entityQuery.error.value.status === 404)

function resetAsOf() {
  asOfLocal.value = ''
  asOfIso.value = null
}
</script>

<template>
  <PageContainer>
    <CompactEmptyState
      v-if="is404"
      icon="icon-[lucide--file-x]"
      :title="t('knowledge.entity.error.notFound')"
      :action-label="t('knowledge.entity.error.notFoundAction')"
      @action="$router.back()"
    />
    <template v-else>
      <EntityDetailToolbar
        v-model:as-of-local="asOfLocal"
        v-model:include-superseded="includeSuperseded"
        @reset="resetAsOf"
      />
      <AnchorNavLayout :sections="sections">
        <section id="entity-metadata" class="space-y-4">
          <Skeleton v-if="entityQuery.isLoading.value" class="h-40 w-full" />
          <EntityMetadataCard v-else-if="entityQuery.data.value" :entity="entityQuery.data.value" />
        </section>
        <section id="entity-timeline" class="space-y-4 mt-6">
          <h2 class="text-sm font-semibold">{{ t('knowledge.entity.sections.timeline') }}</h2>
          <Skeleton v-if="timelineQuery.isLoading.value" class="h-48 w-full" />
          <EntityVersionTimeline v-else-if="timelineQuery.data.value?.length" :nodes="timelineQuery.data.value" />
          <CompactEmptyState
            v-else
            :title="t('knowledge.entity.empty.timelineTitle')"
            :description="t('knowledge.entity.empty.timelineBody')"
          />
        </section>
        <section id="entity-related" class="space-y-4 mt-6">
          <h2 class="text-sm font-semibold">{{ t('knowledge.entity.sections.related') }}</h2>
          <Skeleton v-if="relatedQuery.isLoading.value" class="h-32 w-full" />
          <EntityRelationTree
            v-else-if="relatedQuery.data.value?.length"
            :related="relatedQuery.data.value"
            :current-entity-id="entityId"
          />
          <CompactEmptyState
            v-else
            :title="t('knowledge.entity.empty.relatedTitle')"
            :description="t('knowledge.entity.empty.relatedBody')"
          />
        </section>
      </AnchorNavLayout>
    </template>
  </PageContainer>
</template>
