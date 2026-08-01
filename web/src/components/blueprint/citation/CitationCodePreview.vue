<script setup lang="ts">
/**
 * 代码位置引用预览（Phase 115-03 建，⭐ **116-07 升级为真正的代码预览**）。
 *
 * **渲染的是**：文件路径面包屑 + `line_start..line_end` 行号区间徽标 + ⭐ **当前源码正文**
 * （`<pre class="font-mono">` + 行号列，与 `pseudocode` 块同一套渲染）+ ⭐ **citation 指向的
 * 那几行的行高亮**；取不到正文时回落 citation 自带的 `quote` 快照。
 * ⛔ **不引任何代码编辑器内核 / 语法高亮库** —— 本组件只多了「正文与行号」这份**数据**，
 * 呈现形态与 115-03 逐字一致。
 *
 * **设计沿革（为什么 115 做不到，⛔ 不是遗漏）**：115 相位实测的三条证据链——
 * - `chunk_lookup._query_covering_chunks` 只 select `{chunk_id, file_path, line_start,
 *   line_end, chunk_index}`，`chunk-at` 返 `{path, line, chunks}` —— **不带正文**；
 * - 当时唯一带正文的读面是 `POST /api/repositories/<id>/search/`（向量检索：必须给 query、
 *   已重排过滤），**无法按 path + 行号区间取**；
 * - MCP 的单文件读取工具是 PAT 认证的，SPA 的 cookie-JWT 走不通。
 * ⇒ 该读面当时被顺延，并已由 **116-07** 补上：`GET /repositories/<id>/file-lines/`
 * （实现与 MCP 面共享 `services/repo_file_read.py` 那唯一一份，含 fail-closed 排除判定）。
 *
 * ⭐ **两个判据都是 `usable`，不是状态码**（P-3）：`chunk-at` 对「无命中」与「文件被排除规则
 * 挡掉」统一返回 **200 `{"chunks": []}`**；`file-lines` 对「被排除 / 不存在 / 无镜像」返回
 * **逐字相同的 200 空 `lines`**（两者都是刻意不可区分的存在性防线）。判据分别封装在
 * `getChunkAt` / `getRepositoryFileLines` 的返回值里，本组件只消费它们。
 * `locator.line_start` 缺失时**两个请求都不发** —— 后端行号参数均为必填，发出去也是注定
 * 失败的往返。
 *
 * ⛔ 任何分支都不回显后端错误体（会泄露内部路径与参数校验细节，T-115-23）；⛔ 任何失败都
 * 只降级、**不关弹窗**（115-03 立的既有纪律）。
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

/* ------------------------------------------------------------------ *
 * ⭐ 116-07：当前源码正文 + citation 区间行高亮
 * ------------------------------------------------------------------ */

/** citation 指向的区间（`line_end` 缺失时退化成单行）——高亮与请求区间都以它为准。 */
const citationEnd = computed(() => lineEnd.value ?? lineStart.value)

const { data: fileLines, isPending: sourcePending } = useQuery({
  queryKey: computed(() => [
    'blueprint',
    'citation',
    'file_lines',
    props.repositoryId,
    filePath.value,
    lineStart.value,
    citationEnd.value,
  ]),
  queryFn: () => repositoryChunksApi.getRepositoryFileLines(props.repositoryId, {
    path: filePath.value,
    lineStart: lineStart.value as number,
    lineEnd: citationEnd.value as number,
    ...(branchName.value ? { branchName: branchName.value } : {}),
  }),
  enabled: canQuery,
  staleTime: 5 * 60_000,
  retry: false,
})

/** `getRepositoryFileLines` 恒不抛：`usable === false` 已覆盖非 2xx、网络失败与 200-空 lines。 */
const sourceUsable = computed(() => Boolean(fileLines.value?.usable))
const sourceLines = computed(() => fileLines.value?.lines ?? [])
const sourceTruncated = computed(() => Boolean(fileLines.value?.truncated))

/**
 * 两个查询都落地了才算加载完 —— 否则 `chunk-at` 先回来会让快照先闪一下再被正文替换。
 * ⛔ 仍然只在 `canQuery` 为真时才算加载中（缺 `line_start` 时一个请求都不发）。
 */
const previewLoading = computed(() => loading.value || (canQuery.value && sourcePending.value))

/** ⭐ 高亮判据只看 citation 的 `locator` 区间：后端返回更宽的上下文时也只高亮被引的那几行。 */
function isCited(lineNo: number): boolean {
  const start = lineStart.value
  if (start === null)
    return false
  return lineNo >= start && lineNo <= (citationEnd.value ?? start)
}
</script>

<template>
  <div class="space-y-3">
    <Skeleton v-if="previewLoading" class="h-24 w-full" />

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

      <!-- ⭐ 当前源码正文 + 行号列 + citation 区间行高亮（116-07 补上的读面） -->
      <div
        v-if="sourceUsable"
        class="rounded-md border border-border/50 bg-muted/20"
        data-testid="citation-code-source"
      >
        <p class="border-b border-border/40 px-2.5 py-1 text-[11px] text-muted-foreground">
          {{ t('knowledge.blueprints.citation.sourceText') }}
        </p>
        <div class="overflow-x-auto">
          <div
            v-for="row in sourceLines"
            :key="row.line_no"
            class="flex items-start"
            :class="isCited(row.line_no) ? 'bg-primary/10' : ''"
            :data-citation-highlight="isCited(row.line_no) ? 'true' : 'false'"
            :data-line-no="row.line_no"
            data-testid="citation-code-line"
          >
            <span class="min-w-[3rem] select-none px-2 text-right font-mono text-xs leading-6 text-muted-foreground/60">{{ row.line_no }}</span>
            <pre class="flex-1 whitespace-pre-wrap pr-3 font-mono text-xs leading-6">{{ row.text }}</pre>
          </div>
        </div>
        <p
          v-if="sourceTruncated"
          class="border-t border-border/40 px-2.5 py-1 text-[11px] text-muted-foreground"
          data-testid="citation-code-truncated"
        >
          {{ t('knowledge.blueprints.citation.sourceTruncated', { n: sourceLines.length }) }}
        </p>
      </div>

      <!-- 取不到正文时回落 citation 的 quote 快照（⚠️ 是引用时的快照，不是当前源码） -->
      <div v-else-if="quoteLines.length" class="rounded-md border border-border/50 bg-muted/20">
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
