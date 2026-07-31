<script setup lang="ts">
/**
 * 引用角标（Phase 115-03，UI-SPEC §6.2 citation chip 行 / §10.1 分流）。
 *
 * **职责**：把文档级引用池里的一条 `Citation` 渲染成块底部那一枚 `[n] 定位串` 角标，
 * 并决定它是**外链直达**还是**触发二级预览**。
 *
 * **安全**：`title` / `quote` / `locator` 全是 LLM 合成的半可信文本，全程 Vue mustache，
 * 未使用任何原始 HTML 注入指令，XSS 面 = 0。外链一律带 `rel="noopener noreferrer"`，
 * 且只接受 `http(s)` 协议（⛔ 挡掉 `javascript:` / `data:` 之类的伪协议）。
 *
 * **分流**（⛔ 不得合并成一种）：
 * - `work_item` / `feishu_doc` / `url` ⇒ `<a target="_blank">` 新页打开，**不 emit、不弹 Dialog**
 *   （站外来源没有站内预览面，弹一个空壳弹层只会让人以为「加载失败」）；
 * - 其余六类 ⇒ `<button>` emit `click`，由页面打开 `CitationPreviewDialog`。
 */

import type { Citation, CitationSourceType } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  citation: Citation
  /** 块内序号（从 1 起，仅用于展示 `[n]`）。 */
  index: number
}>()

const emit = defineEmits<{
  click: [citationId: string]
}>()

const { t } = useI18n()

/** 九档 `source_type` → 裸图标名（形状照 `~/components/knowledge/EntityKindBadge.vue` 的映射表）。 */
const SOURCE_ICON: Record<CitationSourceType, string> = {
  knowledge_entity: 'lucide--book-open',
  repo_file: 'lucide--file-code',
  rag_chunk: 'lucide--file-code',
  repo_charter: 'lucide--scroll-text',
  blueprint: 'lucide--file-text',
  artifact_version: 'lucide--file-text',
  work_item: 'lucide--list-checks',
  feishu_doc: 'lucide--external-link',
  url: 'lucide--external-link',
}

/** 九档 `source_type` → i18n 文案键尾段（`knowledge.blueprints.citation.*`）。 */
const SOURCE_LABEL_KEY: Record<CitationSourceType, string> = {
  knowledge_entity: 'sourceKnowledgeEntity',
  repo_file: 'sourceRepoFile',
  rag_chunk: 'sourceRagChunk',
  repo_charter: 'sourceRepoCharter',
  blueprint: 'sourceBlueprint',
  artifact_version: 'sourceArtifactVersion',
  work_item: 'sourceWorkItem',
  feishu_doc: 'sourceFeishuDoc',
  url: 'sourceUrl',
}

/** ⭐ 走 `<a>` 直达、**不进二级预览**的三类站外来源。 */
const EXTERNAL_SOURCE_TYPES = new Set<string>(['work_item', 'feishu_doc', 'url'])

/** 视觉类串逐字照 UI-SPEC §6.2；焦点环见下方 docstring。 */
const CHIP_CLASS = 'inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[11px] font-mono text-muted-foreground hover:border-primary/40 hover:text-primary'

/**
 * 焦点环用**不透明** teal-600（3.74:1）。
 * ⛔ 不复制既有 `.btn:focus-visible` 的 50% 透明 teal-500（实算 1.59:1，未过 WCAG 2.4.11）。
 */
const CHIP_FOCUS_CLASS = 'outline-none focus-visible:[outline:2px_solid_var(--color-primary-600)] focus-visible:[outline-offset:2px]'

const icon = computed(() => SOURCE_ICON[props.citation.source_type] ?? 'lucide--file-text')

const sourceLabel = computed(() => {
  const key = SOURCE_LABEL_KEY[props.citation.source_type]
  return key ? t(`knowledge.blueprints.citation.${key}`) : props.citation.source_type
})

function readString(bag: Record<string, unknown> | undefined, key: string): string {
  const value = bag?.[key]
  return typeof value === 'string' ? value : ''
}

function readNumber(bag: Record<string, unknown> | undefined, key: string): number | null {
  const value = bag?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * 展示串：优先 `title` 快照，其次由 `locator` 拼出 `path:start-end`，再退到来源类型文案。
 * ⚠️ `locator` 运行期形状无 schema 保证 ⇒ 逐键收窄，⛔ 不做 `as` 断言。
 */
const label = computed(() => {
  const { title, locator, source_id: sourceId } = props.citation
  if (title)
    return title

  const path = readString(locator, 'file_path') || readString(locator, 'path')
  if (path) {
    const start = readNumber(locator, 'line_start')
    const end = readNumber(locator, 'line_end')
    if (start !== null)
      return end !== null ? `${path}:${start}-${end}` : `${path}:${start}`
    return path
  }

  const heading = readString(locator, 'heading')
  if (heading)
    return heading

  return sourceId || sourceLabel.value
})

const isExternal = computed(() => EXTERNAL_SOURCE_TYPES.has(props.citation.source_type))

/** ⭐ 只接受 `http(s)`：其余协议（含 `javascript:`）一律判为无链接，退化成非交互 `<span>`。 */
const href = computed(() => {
  const { locator, source_id: sourceId } = props.citation
  const raw = readString(locator, 'url') || (typeof sourceId === 'string' ? sourceId : '')
  return /^https?:\/\//i.test(raw) ? raw : ''
})

const ariaLabel = computed(() =>
  isExternal.value
    ? t('knowledge.blueprints.citation.openExternal')
    : t('knowledge.blueprints.citation.open', { title: label.value }),
)
</script>

<template>
  <a
    v-if="isExternal && href"
    :href="href"
    target="_blank"
    rel="noopener noreferrer"
    :class="[CHIP_CLASS, CHIP_FOCUS_CLASS]"
    :aria-label="ariaLabel"
    :title="label"
    data-testid="blueprint-citation-chip"
    :data-source-type="citation.source_type"
    data-citation-external="true"
  >
    <span class="shrink-0 text-[11px]" :class="`icon-[${icon}]`" aria-hidden="true" />
    <span>[{{ index }}]</span>
    <span class="truncate max-w-[22rem]">{{ label }}</span>
  </a>

  <span
    v-else-if="isExternal"
    :class="CHIP_CLASS"
    :title="label"
    data-testid="blueprint-citation-chip"
    :data-source-type="citation.source_type"
    data-citation-external="true"
  >
    <span class="shrink-0 text-[11px]" :class="`icon-[${icon}]`" aria-hidden="true" />
    <span>[{{ index }}]</span>
    <span class="truncate max-w-[22rem]">{{ label }}</span>
  </span>

  <button
    v-else
    type="button"
    :class="[CHIP_CLASS, CHIP_FOCUS_CLASS]"
    :aria-label="ariaLabel"
    :title="label"
    data-testid="blueprint-citation-chip"
    :data-source-type="citation.source_type"
    @click="emit('click', citation.citation_id)"
  >
    <span class="shrink-0 text-[11px]" :class="`icon-[${icon}]`" aria-hidden="true" />
    <span>[{{ index }}]</span>
    <span class="truncate max-w-[22rem]">{{ label }}</span>
  </button>
</template>
