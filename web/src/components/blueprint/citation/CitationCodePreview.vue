<script setup lang="ts">
/**
 * 代码位置引用预览（Phase 115-03）——⭐ **本相位显式降级形态**。
 *
 * **渲染的是**：文件路径面包屑 + `line_start..line_end` 行号区间 + citation 自带的 `quote`
 * 快照（`<pre class="font-mono">` + 行号列，与 `pseudocode` 块同一套渲染）。
 * **⛔ 没有源码正文、⛔ 没有代码编辑器内核、因而也没有行高亮。**
 *
 * **降级的证据链**（115-02 已把它登记为 UI-SPEC §3.6/§10.1 的订正，本组件落地）：
 * - `chunk_lookup._query_covering_chunks` 只 select `{chunk_id, file_path, line_start,
 *   line_end, chunk_index}`，`chunk_at_views` 返 `{path, line, chunks}` —— **不带正文**；
 * - 全仓唯一带正文的读面是 `POST /api/repositories/<id>/search/`（向量检索：必须给 query、
 *   已重排过滤），**无法按 path + 行号区间取**；
 * - 仓内没有只读代码编辑器封装（`components/execution/JsonViewer.vue` 自承是它的替代品）。
 * ⇒ 「按 path + 行区间取源码」的读面归 **Phase 116**，⛔ 115 不为此新增后端端点。
 *
 * ⭐ **兜底判据是 `usable`，不是状态码**（P-3）：`chunk-at` 对「无命中」与「文件被排除规则
 * 挡掉」统一返回 **200 `{"chunks": []}`**（刻意不可区分的存在性防线）。判据封装在 115-02 的
 * `getChunkAt` 返回值里，本组件只消费它。`locator.line_start` 缺失时**直接不发请求** ——
 * 后端 `path` 与 `line` 均为必填，发出去也是注定失败的一次往返。
 *
 * ⛔ 任何分支都不回显后端错误体（会泄露内部路径与参数校验细节，T-115-23）。
 */

import type { RepoChunkRef } from '~/api/repositoryChunks'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { repositoryChunksApi } from '~/api'
import { Skeleton } from '~/components/ui/skeleton'
import CitationFallback from './CitationFallback.vue'

const props = withDefaults(defineProps<{
  repositoryId?: string
  /** citation 的定位信息；运行期形状无 schema 保证 ⇒ 逐键收窄。 */
  locator?: Record<string, unknown>
  fallback?: { title?: string, quote?: string }
}>(), {
  repositoryId: '',
  locator: () => ({}),
  fallback: () => ({}),
})

const { t } = useI18n()

function readString(key: string): string {
  const value = props.locator?.[key]
  return typeof value === 'string' ? value : ''
}

function readNumber(key: string): number | null {
  const value = props.locator?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const filePath = computed(() => readString('file_path') || readString('path'))
const lineStart = computed(() => readNumber('line_start'))
const lineEnd = computed(() => readNumber('line_end'))
const branchName = computed(() => readString('branch_name'))

/** ⭐ 缺 `line_start`（或缺仓库 / 路径）⇒ 查询根本不启用，一次请求都不发。 */
const canQuery = computed(
  () => Boolean(props.repositoryId) && Boolean(filePath.value) && lineStart.value !== null,
)

const { data, isPending } = useQuery({
  queryKey: computed(() => [
    'blueprint',
    'citation',
    'repo_chunk',
    props.repositoryId,
    filePath.value,
    lineStart.value,
  ]),
  queryFn: () => repositoryChunksApi.getChunkAt(props.repositoryId, {
    path: filePath.value,
    line: lineStart.value as number,
    ...(branchName.value ? { branch_name: branchName.value } : {}),
  }),
  enabled: canQuery,
  staleTime: 5 * 60_000,
  retry: false,
})

const loading = computed(() => canQuery.value && isPending.value)

/** `getChunkAt` 恒不抛：`usable === false` 已覆盖 400 / 404 / 5xx / 网络失败 / 200-空 chunks。 */
const usable = computed(() => Boolean(data.value?.usable))

const chunks = computed<RepoChunkRef[]>(() => data.value?.chunks ?? [])
const primaryChunk = computed<RepoChunkRef | null>(() => chunks.value[0] ?? null)

/** 行号区间：优先用命中 chunk 的真实区间，取不到回落 citation 的 locator。 */
const rangeStart = computed(() => primaryChunk.value?.line_start ?? lineStart.value ?? 0)
const rangeEnd = computed(() => primaryChunk.value?.line_end ?? lineEnd.value ?? rangeStart.value)

const displayPath = computed(() => primaryChunk.value?.file_path || filePath.value)
const pathSegments = computed(() => displayPath.value.split('/').filter(Boolean))

/** quote 快照按行切开，行号从区间起点起算（⚠️ 这是**引用时的快照**，不是当前源码）。 */
const quoteLines = computed(() => {
  const quote = props.fallback?.quote ?? ''
  return quote ? quote.split('\n') : []
})
</script>

<template>
  <div class="space-y-3">
    <Skeleton v-if="loading" class="h-24 w-full" />

    <CitationFallback
      v-else-if="!usable"
      :title="fallback?.title"
      :quote="fallback?.quote"
    />

    <template v-else>
      <!-- 文件路径面包屑 + 行号区间徽标 -->
      <div class="flex flex-wrap items-center gap-1 text-xs" data-testid="citation-code-path">
        <template v-for="(segment, i) in pathSegments" :key="i">
          <span v-if="i > 0" class="text-muted-foreground/50">/</span>
          <span class="font-mono" :class="i === pathSegments.length - 1 ? 'text-foreground' : 'text-muted-foreground'">{{ segment }}</span>
        </template>
        <span class="ml-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
          {{ t('knowledge.blueprints.citation.lineRange', { start: rangeStart, end: rangeEnd }) }}
        </span>
      </div>

      <p v-if="chunks.length > 1" class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.citation.chunkCount', { n: chunks.length }) }}
      </p>

      <!-- quote 快照（⛔ 不是当前源码：本相位没有按 path + 行区间取正文的读面） -->
      <div v-if="quoteLines.length" class="rounded-md border border-border/50 bg-muted/20">
        <p class="border-b border-border/40 px-2.5 py-1 text-[11px] text-muted-foreground">
          {{ t('knowledge.blueprints.annotation.quotedSnapshot') }}
        </p>
        <div class="overflow-x-auto">
          <div v-for="(line, i) in quoteLines" :key="i" class="flex items-start">
            <span class="min-w-[3rem] select-none px-2 text-right font-mono text-xs leading-6 text-muted-foreground/60">{{ rangeStart + i }}</span>
            <pre class="flex-1 whitespace-pre-wrap pr-3 font-mono text-xs leading-6">{{ line }}</pre>
          </div>
        </div>
      </div>
      <p v-else class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.citation.fallback') }}
      </p>
    </template>
  </div>
</template>
