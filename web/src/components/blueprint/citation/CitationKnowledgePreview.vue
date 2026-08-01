<script setup lang="ts">
/**
 * 知识实体引用预览（Phase 115-03，UI-SPEC §10.1 分发表第一行）。
 *
 * **渲染的是**：实体元数据卡（标题 / 种类 / 版本 / 来源 / 生效时间）+ citation 自带的 `quote`
 * 快照 + 「在知识库中打开」的站内跳转。
 *
 * ⚠️ **正文渲染器未被引入，这是实测结论不是遗漏**：`GET /knowledge/entities/<id>/` 的响应
 * （`EntityMetadata`，`web/src/api/knowledge.ts:10-25`）只有 14 个元数据键，**没有任何正文
 * 字段**；实体详情页 `pages/knowledge/entities/[id].vue` 同样只渲染元数据 + 版本轨 + 关联，
 * 全仓不存在「取知识实体正文」的读面。⇒ 正文位改用 citation 的 `quote` 快照，
 * ⛔ 不引 `MarkdownRenderer`（它拿不到内容，只会渲染一个空壳）。
 *
 * ⛔ **不调知识库的「关联实体」与「工件关联」两个读面**（P-5）：它们查的是
 * `initiatives.Artifact` 投影出来的知识实体，拿蓝图的 `delivery.Artifact.id` 去调必然
 * 404 / 空集。本相位只调 `getEntity` 这一个只读面。
 *
 * **兜底**：任何失败（含 404）一律 `CitationFallback`，⛔ **不关弹窗**、⛔ 不回显后端错误体。
 */

import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { knowledgeApi } from '~/api'
import { Skeleton } from '~/components/ui/skeleton'
import CitationFallback from './CitationFallback.vue'

const props = withDefaults(defineProps<{
  entityId?: string
  fallback?: { title?: string, quote?: string }
}>(), {
  entityId: '',
  fallback: () => ({}),
})

const { t } = useI18n()

const canQuery = computed(() => Boolean(props.entityId))

const { data, isPending, isError } = useQuery({
  queryKey: computed(() => ['blueprint', 'citation', 'knowledge_entity', props.entityId]),
  queryFn: () => knowledgeApi.getEntity(props.entityId),
  enabled: canQuery,
  staleTime: 5 * 60_000,
  retry: false,
})

const loading = computed(() => canQuery.value && isPending.value)
const degraded = computed(() => !canQuery.value || isError.value || !data.value)

const metaRows = computed(() => {
  const entity = data.value
  if (!entity)
    return []
  return [
    { label: t('knowledge.entity.fields.version'), value: String(entity.version ?? '') },
    { label: t('knowledge.entity.fields.entityId'), value: entity.entity_id ?? '' },
    { label: t('knowledge.entity.fields.validAt'), value: entity.valid_at ?? '' },
  ].filter(row => row.value)
})
</script>

<template>
  <div class="space-y-3">
    <Skeleton v-if="loading" class="h-24 w-full" />

    <CitationFallback
      v-else-if="degraded"
      :title="fallback?.title"
      :quote="fallback?.quote"
    />

    <template v-else>
      <div data-testid="citation-knowledge-meta" class="rounded-md border border-border/50 bg-muted/20 p-3">
        <p class="text-sm font-medium text-foreground">
          {{ data?.title }}
        </p>
        <dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <template v-for="row in metaRows" :key="row.label">
            <dt>{{ row.label }}</dt>
            <dd class="font-mono break-all">
              {{ row.value }}
            </dd>
          </template>
        </dl>
      </div>

      <!-- 正文位：站内无实体正文读面 ⇒ 渲染引用时的原文快照 -->
      <div v-if="fallback?.quote" class="space-y-1">
        <p class="text-[11px] text-muted-foreground">
          {{ t('knowledge.blueprints.annotation.quotedSnapshot') }}
        </p>
        <pre class="whitespace-pre-wrap rounded-md border border-border/50 bg-muted/20 p-3 text-sm">{{ fallback.quote }}</pre>
      </div>

      <RouterLink
        :to="`/knowledge/entities/${entityId}`"
        class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
      >
        <span class="icon-[lucide--book-open] text-[12px]" aria-hidden="true" />
        {{ t('knowledge.blueprints.citation.openExternal') }}
      </RouterLink>
    </template>
  </div>
</template>
