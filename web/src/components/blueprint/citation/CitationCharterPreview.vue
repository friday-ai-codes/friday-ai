<script setup lang="ts">
/**
 * 仓库章程引用预览（Phase 115-03，UI-SPEC §10.1 分发表第四行）。
 *
 * **渲染的是**：章程的四个分区 —— 定位（`positioning`）/ 归属域（`owned_domains`）/
 * 边界（`boundaries`）/ 落点偏好（`placement_preferences`）。⚠️ 键名取自 115-02 实测封装的
 * `RepoCharter`（`web/src/api/repositoryChunks.ts:52-69`），⛔ 不猜。
 *
 * 后三项在后端是零约束 JSON 字段 ⇒ 类型为 `unknown`，渲染前逐项收窄：字符串数组逐条列出、
 * 其余形状一律 `JSON.stringify` 后走 `<pre>`（全程 mustache，⛔ 不注入 HTML）。
 *
 * ⚠️ **分区小标题本相位缺 i18n 键，故不渲染文字标题**：`knowledge.blueprints.repo.*` 里没有
 * 章程四分区的标签键（全仓亦无 `charter*` 文案键，实测只有 `citation.sourceRepoCharter`
 * =「仓库章程」这一个）。i18n 三处追加点已由 115-02 一次做完并对本相位关闭 ⇒ 按 §13.2
 * **回报而不自补**：分区身份改由 `data-charter-section` 属性承载（供测试与后续接线定位），
 * 卡片整体用既有的「仓库章程」作标题。补齐 4 个键后即可把标题接上，见 115-03-SUMMARY 的
 * 「回报给 115-06 的 i18n 缺口」一节。
 *
 * **兜底**：`getRepositoryCharter` 恒不抛，无章程 / 任何失败返回 `null` ⇒ `CitationFallback`，
 * ⛔ 不关弹窗、⛔ 不回显后端错误体。
 */

import { useQuery } from '@tanstack/vue-query'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { repositoryChunksApi } from '~/api'
import { Skeleton } from '~/components/ui/skeleton'
import CitationFallback from './CitationFallback.vue'

const props = withDefaults(defineProps<{
  repositoryId?: string
  locator?: Record<string, unknown>
  fallback?: { title?: string, quote?: string }
}>(), {
  repositoryId: '',
  locator: () => ({}),
  fallback: () => ({}),
})

const { t } = useI18n()

/** `locator.section` 指向某一分区时给它 2s 的 ring 高亮。 */
const HIGHLIGHT_MS = 2000

const canQuery = computed(() => Boolean(props.repositoryId))

const { data, isPending } = useQuery({
  queryKey: computed(() => ['blueprint', 'citation', 'repo_charter', props.repositoryId]),
  queryFn: () => repositoryChunksApi.getRepositoryCharter(props.repositoryId),
  enabled: canQuery,
  staleTime: 5 * 60_000,
  retry: false,
})

const loading = computed(() => canQuery.value && isPending.value)
const degraded = computed(() => !canQuery.value || !data.value)

/** 把零约束 JSON 字段收窄成可渲染的字符串列表。 */
function toLines(value: unknown): string[] {
  if (typeof value === 'string')
    return value ? [value] : []
  if (Array.isArray(value))
    return value.map(item => (typeof item === 'string' ? item : JSON.stringify(item)))
  if (value && typeof value === 'object')
    return [JSON.stringify(value, null, 2)]
  return []
}

const sections = computed(() => {
  const charter = data.value
  if (!charter)
    return []
  return [
    { key: 'positioning', lines: toLines(charter.positioning) },
    { key: 'owned_domains', lines: toLines(charter.owned_domains) },
    { key: 'boundaries', lines: toLines(charter.boundaries) },
    { key: 'placement_preferences', lines: toLines(charter.placement_preferences) },
  ].filter(section => section.lines.length)
})

const targetSection = computed(() => {
  const value = props.locator?.section
  return typeof value === 'string' ? value : ''
})

const highlighting = ref(true)
onMounted(() => {
  setTimeout(() => {
    highlighting.value = false
  }, HIGHLIGHT_MS)
})
</script>

<template>
  <div class="space-y-3">
    <Skeleton v-if="loading" class="h-24 w-full" />

    <CitationFallback
      v-else-if="degraded || !sections.length"
      :title="fallback?.title"
      :quote="fallback?.quote"
    />

    <template v-else>
      <p class="text-xs font-medium text-foreground">
        {{ t('knowledge.blueprints.citation.sourceRepoCharter') }}
      </p>
      <section
        v-for="section in sections"
        :key="section.key"
        data-testid="citation-charter-section"
        :data-charter-section="section.key"
        class="rounded-md border border-border/50 bg-muted/20 p-3 transition-shadow"
        :class="highlighting && section.key === targetSection ? 'ring-2 ring-primary/60' : ''"
      >
        <ul class="list-disc pl-5 text-sm text-muted-foreground space-y-0.5">
          <li v-for="(line, i) in section.lines" :key="i">
            <pre class="whitespace-pre-wrap font-sans">{{ line }}</pre>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
