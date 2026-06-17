<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { specsApi } from '~/api/specs'
import LoadingState from '~/components/common/LoadingState.vue'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import SddMethodologyBadge from '~/components/repository/SddMethodologyBadge.vue'
import SddSpecStatusBadge from '~/components/spec/SddSpecStatusBadge.vue'
import SpecDeliveryPanel from '~/components/spec/SpecDeliveryPanel.vue'
import SpecReviewTimeline from '~/components/spec/SpecReviewTimeline.vue'
import SpecTransitionActions from '~/components/spec/SpecTransitionActions.vue'

const route = useRoute('/specs/[id]')
const { t } = useI18n()

const specId = computed(() => String(route.params.id))

const { data: spec, isLoading, isError } = useQuery({
  queryKey: ['spec', specId],
  queryFn: () => specsApi.detail(specId.value),
})

const relations = computed(() => spec.value?.relations ?? {})
const heading = computed(
  () => spec.value?.relations.work_item?.title || spec.value?.repository_name || '',
)
</script>

<template>
  <PageContainer>
    <LoadingState v-if="isLoading" variant="skeleton" :text="t('specs.loading')" />
    <div v-else-if="isError || !spec" class="text-sm text-destructive py-8 text-center">
      {{ t('specs.loadError') }}
    </div>
    <template v-else>
      <!-- 头部：状态徽标 + 标题 -->
      <div class="flex items-center gap-3">
        <SddSpecStatusBadge :status="spec.status" />
        <h1 class="text-xl font-semibold truncate">
          {{ heading }}
        </h1>
      </div>

      <!-- 关联链接区（缺失项不渲染） -->
      <div class="flex flex-wrap items-center gap-4 text-sm">
        <RouterLink
          v-if="relations.repository"
          :to="`/repositories/${relations.repository.id}`"
          class="inline-flex items-center gap-1.5 text-primary underline-offset-2 hover:underline"
        >
          <span class="icon-[lucide--git-branch]" aria-hidden="true" />
          {{ relations.repository.name }}
        </RouterLink>
        <SddMethodologyBadge
          v-if="relations.repository?.methodology"
          :methodology="relations.repository.methodology"
        />
        <span
          v-if="relations.work_item"
          class="inline-flex items-center gap-1.5 text-muted-foreground"
        >
          <span class="icon-[lucide--clipboard-list]" aria-hidden="true" />
          {{ t('specs.detail.workItem') }}：{{ relations.work_item.title }}
        </span>
        <span
          v-if="relations.plan_version"
          class="inline-flex items-center gap-1.5 text-muted-foreground"
        >
          <span class="icon-[lucide--file-stack]" aria-hidden="true" />
          {{ t('specs.detail.planVersion') }}：v{{ relations.plan_version.version }}
        </span>
      </div>

      <!-- 正文 -->
      <section class="card p-5 space-y-3">
        <h2 class="text-base font-semibold">
          {{ t('specs.detail.body') }}
        </h2>
        <MarkdownRenderer :content="spec.body || ''" />
      </section>

      <!-- 交付验收追溯面板（WorkItem → spec → 实现 PR 链路，LINK-02） -->
      <SpecDeliveryPanel :spec="spec" />

      <!-- 评审历史 -->
      <section class="card p-5 space-y-3">
        <h2 class="text-base font-semibold">
          {{ t('specs.detail.reviewHistory') }}
        </h2>
        <SpecReviewTimeline :reviews="spec.reviews" />
      </section>

      <!-- 操作区 -->
      <section class="card p-5">
        <SpecTransitionActions :spec="spec" />
      </section>
    </template>
  </PageContainer>
</template>
