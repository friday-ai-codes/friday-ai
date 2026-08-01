<script setup lang="ts">
/**
 * 其它蓝图引用预览（Phase 115-03，UI-SPEC §10.1 分发表第三行 / §18.2）。
 *
 * **渲染的是**：被引蓝图的 `meta.title` + `meta.summary` + **被引块**（按 `blockId` 从
 * `iterBlocks` 的走查结果里定位），底部给「打开完整蓝图」的站内跳转。
 *
 * ⭐ **迷你只读三条**（缺一条都会出问题）：
 * - `readonly` —— 预览里没有任何写入面；
 * - `threads: []` —— **无批注层**：这是别人的蓝图，把当前蓝图的线程画上去就是张冠李戴；
 * - `plainMermaid: true` —— ⭐ 预览弹层内 mermaid 退化为源码 `<pre>`。`MermaidDiagram` 的
 *   放大层用 `vue-final-modal`，与 reka-ui `Dialog` 是**两套模态栈**，在 Dialog 内点放大会
 *   叠放竞争、抢焦点（P-12 次生，T-115-26）。
 *
 * ⭐ **预览内的 citation chip 不开第二层弹层**（§18.2）：本组件**不监听** `BlueprintBlockList`
 * 的 `citation-click`，也⛔ 不引入上层那个引用预览弹层组件（那会造成 Dialog 套 Dialog，
 * 焦点陷阱互相抢）。要继续追溯请走底部的「打开完整蓝图」。
 *
 * **兜底**：任何失败一律 `CitationFallback`，⛔ 不关弹窗、⛔ 不回显后端错误体。
 */

import type { BlueprintBlock as BlueprintBlockModel } from '~/types/blueprint'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { blueprintsApi } from '~/api'
import { Skeleton } from '~/components/ui/skeleton'
import { iterBlocks } from '~/utils/blueprintBlocks'
import BlueprintBlockList from '../BlueprintBlockList.vue'
import CitationFallback from './CitationFallback.vue'

const props = withDefaults(defineProps<{
  artifactId?: string
  versionId?: string
  blockId?: string
  fallback?: { title?: string, quote?: string }
}>(), {
  artifactId: '',
  versionId: '',
  blockId: '',
  fallback: () => ({}),
})

const { t } = useI18n()

const canQuery = computed(() => Boolean(props.artifactId))

const { data, isPending, isError } = useQuery({
  queryKey: computed(() => [
    'blueprint',
    'citation',
    'blueprint',
    props.artifactId,
    props.versionId || 'current',
  ]),
  queryFn: () => blueprintsApi.getBlueprintDocument(
    props.artifactId,
    props.versionId ? { version_id: props.versionId } : undefined,
  ),
  enabled: canQuery,
  staleTime: 5 * 60_000,
  retry: false,
})

const loading = computed(() => canQuery.value && isPending.value)
const degraded = computed(() => !canQuery.value || isError.value || !data.value?.content)

const meta = computed(() => data.value?.content?.meta)
const summaryBlocks = computed<BlueprintBlockModel[]>(() => meta.value?.summary ?? [])

/** 被引块：按 `blockId` 从全文走查结果里定位（⛔ 不自写走查，复用 115-02 的 `iterBlocks`）。 */
const citedBlocks = computed<BlueprintBlockModel[]>(() => {
  if (!props.blockId || !data.value?.content)
    return []
  const hit = iterBlocks(data.value.content).find(item => item.block.block_id === props.blockId)
  return hit ? [hit.block] : []
})

const citations = computed(() => data.value?.content?.citations ?? {})
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
      <p class="text-sm font-medium text-foreground">
        {{ meta?.title }}
      </p>

      <BlueprintBlockList
        v-if="summaryBlocks.length"
        data-testid="citation-blueprint-summary"
        :blocks="summaryBlocks"
        :threads="[]"
        :citations="citations"
        readonly
        plain-mermaid
      />

      <div v-if="citedBlocks.length" class="rounded-md border border-border/50 bg-muted/20 p-3">
        <p class="mb-1 text-[11px] text-muted-foreground">
          {{ t('knowledge.blueprints.annotation.quotedSnapshot') }}
        </p>
        <BlueprintBlockList
          :blocks="citedBlocks"
          :threads="[]"
          :citations="citations"
          readonly
          plain-mermaid
        />
      </div>

      <RouterLink
        :to="`/knowledge/blueprints/${artifactId}`"
        class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
      >
        <span class="icon-[lucide--file-text] text-[12px]" aria-hidden="true" />
        {{ t('knowledge.blueprints.citation.openExternal') }}
      </RouterLink>
    </template>
  </div>
</template>
