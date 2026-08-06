<script setup lang="ts">
/**
 * 蓝图正文单块渲染（Phase 115-03，UI-SPEC §6.2 / §7.1–§7.3 / §7.5）。
 *
 * **职责**：一个 `Block` 进、一段 DOM 出。**批注层与引用层的唯一实现点** —— 五类块分发、
 * 按 `anchor.start_offset/end_offset` 在纯文本上切区间并用 `<mark>` 包裹、块底一行 citation
 * chip，三件事都只在这里做。九个 section 组件（115-05）一律经 `BlueprintBlockList` 透传
 * `blockCtx`，⛔ 不在段组件里重复实现批注与引用。
 *
 * **安全**：块文本、citation `quote` / `title`、表格单元格全程 Vue mustache + `<pre>`，
 * 未使用任何原始 HTML 注入指令，XSS 面 = 0。区间切分由 `sliceBlockText` 返回**结构化数组**，
 * 渲染层只做 `v-for`，⛔ 不拼 HTML 串（T-115-21）。
 *
 * **坐标系**：块文本一律经 `blockText(block)`（`~/utils/blueprintBlocks`），它按
 * `text → code.source → rows` 的**字段优先级**取值、**不看 `block.type`** —— 与后端
 * `_block_text`（`server/delivery/services/blueprint_anchor.py:34-64`）逐字同源。
 * ⛔ 组件内不得自行按 type 取文本：坐标系不一致的后果是 offset 仍落在合法范围内 ⇒
 * 不触发降级、不报错、`<mark>` 照渲，**只是圈错了字**（P-13）。
 *
 * **三态不混**（§7.3）：前端越界降级 ⇒ 整块色条 + 计数角标，线程**仍按 `status` 归组**；
 * 后端失锚（`anchor_status === 'orphaned'`）⇒ 正文**完全不渲染**任何标记；
 * `table` / `mermaid` ⇒ 强制整块（前者 offset 坐标系是「单元格扁平后 `\n` 连接」，
 * 与渲染出的 `<table>` 无法映射；后者渲染的是 SVG）。
 *
 * ⚠️ mermaid 空源码必须由**调用方 `v-if`** 判空 —— 组件自身会渲一个空 `<pre>` 且无提示。
 */

import type { BlueprintBlock as BlueprintBlockModel, BlueprintFeaturePoint, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import type { TextSegment } from '~/utils/blueprintAnnotations'
import type { InlineStyleKind, MarkdownLineKind, MarkdownLineMeta } from '~/utils/blueprintMarkdownLite'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import MermaidDiagram from '~/components/project/warroom/MermaidDiagram.vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import {
  anchorRangesForBlock,
  degradedThreadIds,
  isValidAnchor,
  sliceBlockText,
} from '~/utils/blueprintAnnotations'
import { blockText } from '~/utils/blueprintBlocks'
import {
  intentLabelKeyOf,
  matchFeaturePointsToRenderedLines,
} from '~/utils/blueprintFeaturePoints'
import { buildMarkdownRender, isMarkdownishText } from '~/utils/blueprintMarkdownLite'
import { annotationClass, MARK_BASE_CLASS, pickTopThread } from './annotationTokens'
import BlueprintCitationChip from './BlueprintCitationChip.vue'

const props = withDefaults(defineProps<{
  block: BlueprintBlockModel
  /** 仅用于降级定位与失锚回显文案，⛔ **不参与 DOM id**（DOM id 一律 `blk-${block_id}`）。 */
  sectionPath?: string
  /** 已按 `block_id` 预分组的线程（由 `BlueprintBlockList` 经 `groupThreadsByBlock` 给出）。 */
  threads?: BlueprintThreadDetail[]
  /** 文档级引用池 `content.citations`（是 object 不是 array）。 */
  citations?: Record<string, Citation>
  /**
   * 契约对齐用：本组件**没有任何写入面**（无 block 编辑入口，§0.1 硬边界第 3 条），
   * 该 prop 只为 115-05/06 的透传链保持签名一致。
   */
  readonly?: boolean
  activeThreadId?: string | null
  /** 已关闭（`resolved` / `dismissed`）的批注默认不着色，由顶栏开关放出（§7.5）。 */
  showClosed?: boolean
  /**
   * ⭐ 引用预览弹层内传 `true`：mermaid 块退化为源码 `<pre>`。
   * `MermaidDiagram` 的放大层用 `vue-final-modal`，与 reka-ui `Dialog` 是两套模态栈，
   * 在 Dialog 内点放大会叠放竞争（P-12 次生，T-115-26）。
   */
  plainMermaid?: boolean
  /**
   * 功能点内联标签（quick-260806：功能点分散进目标正文，只有需求规格的 goal 块传）。
   * 匹配到的行在行尾渲染 `fp_<id> · 状态` 小标签并挂 `fp-<id>` 跳转锚点。
   * ⭐ 标签是**零文本节点**元素（文字走 CSS `content: attr(...)` 伪元素）——
   * 与任务框替代物同一条纪律：不污染 `rangeOffsets` 的扁平选区坐标系。
   */
  featurePoints?: BlueprintFeaturePoint[]
}>(), {
  sectionPath: '',
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
  plainMermaid: false,
  featurePoints: () => [],
})

const emit = defineEmits<{
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
}>()

const { t } = useI18n()

/** 线程种类 → i18n 文案键（`<mark>` 的 `aria-label` 用）。 */
const KIND_LABEL_KEY: Record<string, string> = {
  ai_clarification: 'kindAiClarification',
  ai_review_finding: 'kindAiReviewFinding',
  human_comment: 'kindHumanComment',
  repo_confirmation: 'kindRepoConfirmation',
}

const CLOSED_STATUSES = new Set<string>(['resolved', 'dismissed'])

/** ⭐ 唯一取文本口径，⛔ 不按 `block.type` 分派。 */
const text = computed(() => blockText(props.block))

/**
 * 参与正文标记的线程：只收锚在本块上的 anchored 线程。
 * ⭐ `orphaned` 的线程在正文**完全不渲染**任何标记（连整块色条都不给，§7.3）。
 */
const anchoredThreads = computed(() =>
  (props.threads ?? []).filter(
    thread => thread?.anchor_status !== 'orphaned'
      && thread?.anchor?.block_id === props.block.block_id,
  ),
)

/** 已关闭的批注默认隐藏（`showClosed` 打开后按点线档着色）。 */
const visibleThreads = computed(() =>
  anchoredThreads.value.filter(
    thread => props.showClosed || !CLOSED_STATUSES.has(thread.status),
  ),
)

const ranges = computed(() => anchorRangesForBlock(visibleThreads.value))

/** `table` / `mermaid` 的 offset 无法映射到渲染 DOM ⇒ 强制整块，⛔ 不做字符级划线。 */
const forcedWholeBlock = computed(
  () => props.block.type === 'table' || props.block.type === 'mermaid',
)

/** 是否存在越界 / 非整数 / `start >= end` 的 anchor（前端降级判据，⛔ 与后端失锚无关）。 */
const hasInvalidAnchor = computed(
  () => ranges.value.some(range => !isValidAnchor(range, text.value.length)),
)

/** 走整块降级的线程集合：强制档取全部可见线程，否则只取 anchor 不合法的那些。 */
const degradedThreads = computed(() => {
  if (forcedWholeBlock.value)
    return visibleThreads.value
  if (!hasInvalidAnchor.value)
    return []
  const ids = new Set(degradedThreadIds(text.value, ranges.value))
  return visibleThreads.value.filter(thread => ids.has(thread.thread_id))
})

const isDegraded = computed(() => degradedThreads.value.length > 0)

/** 整块色条取**优先级最高**那条线程的色（唯一颜色来源是 `annotationClass`）。 */
const degradedClass = computed(() => {
  const top = pickTopThread(degradedThreads.value)
  if (!top)
    return ''
  return annotationClass(top.kind, top.severity, top.status, top.thread_id === props.activeThreadId)
})

/** 渲染用的切分段（比 `TextSegment` 多带着色与 a11y 属性，避免模板里反复查表）。 */
interface RenderSegment {
  text: string
  threadIds: string[]
  mark: boolean
  cls: string
  label: string
  topThreadId: string
  severity: string
  status: string
}

const threadById = computed(() => {
  const map: Record<string, BlueprintThreadDetail> = {}
  for (const thread of visibleThreads.value)
    map[thread.thread_id] = thread
  return map
})

function kindLabel(kind: string | undefined): string {
  const key = kind ? KIND_LABEL_KEY[kind] : ''
  return key ? t(`knowledge.blueprints.thread.${key}`) : ''
}

function decorate(segment: TextSegment): RenderSegment {
  const threads = segment.threadIds
    .map(id => threadById.value[id])
    .filter((thread): thread is BlueprintThreadDetail => Boolean(thread))
  const top = pickTopThread(threads)
  if (!top) {
    return {
      text: segment.text,
      threadIds: [],
      mark: false,
      cls: '',
      label: '',
      topThreadId: '',
      severity: '',
      status: '',
    }
  }
  const active = props.activeThreadId !== null
    && segment.threadIds.includes(props.activeThreadId as string)
  return {
    text: segment.text,
    threadIds: segment.threadIds,
    mark: true,
    cls: annotationClass(top.kind, top.severity, top.status, active),
    label: t('knowledge.blueprints.annotation.markLabel', {
      count: threads.length,
      kind: threads.map(thread => kindLabel(thread.kind)).join('、'),
    }),
    topThreadId: top.thread_id,
    severity: top.severity,
    status: top.status,
  }
}

/** 强制整块档不做切分（切了也不会渲染成 `<mark>`，白算一遍）。 */
const segments = computed<TextSegment[]>(() =>
  forcedWholeBlock.value ? [] : sliceBlockText(text.value, ranges.value),
)

const paragraphSegments = computed(() => segments.value.map(decorate))

// ── markdown 预览渲染（quick-260806-gfk v3：渲染映射）──────────────────────────
//
// 机械 intake 会把整段 feature-list markdown 塞进一个 paragraph 块（如
// requirement_spec.goal），裸渲染是一面带 `##`/`- [ ]`/`**` 记号的文字墙。
//
// ⭐ 本分支 DOM 里只放**渲染文本**（记号已删除）：`buildMarkdownRender` 维护
// 「源 ↔ 渲染」保留区间映射 ——
// - 批注锚点（源坐标）经 `toRendered` 换算后在渲染文本上切 `<mark>`；
// - 选区（DOM 即渲染坐标）由 `BlueprintBlockList` 经 `toSource` 换算回源坐标上报；
// - 勾选框/圆点等视觉替代物是 iconify 元素 / 伪元素（**不产生文本节点**，
//   不污染 `rangeOffsets` 的扁平坐标系）。
// 行尾 `\n` 保留在行 div 末段文本节点里（块级末行分隔被浏览器丢弃，视觉无副作用）。

const renderModel = computed(() =>
  props.block.type === 'paragraph' && isMarkdownishText(text.value)
    ? buildMarkdownRender(text.value)
    : null,
)

// ── 功能点内联标签（quick-260806：功能点分散进目标正文）─────────────────────────
//
// 匹配到功能点标题的行在行尾出一枚 `fp_<id> · 状态` 小标签，并承载 `fp-<id>` 跳转锚点
// （现状分析/实现概述/澄清向导的 goto-anchor 落点）。⭐ 标签零文本节点：文字全部走
// CSS `content: attr(...)` 伪元素（与任务框替代物同款纪律），选区坐标系不受影响。

/** 行起点（渲染坐标）→ 功能点标签。只有 goal 块会拿到非空 `featurePoints`。 */
const fpTagByLineStart = computed(() => {
  const model = renderModel.value
  if (!model || !props.featurePoints.length)
    return new Map<number, { pointId: string, intent: string, title: string }>()
  return matchFeaturePointsToRenderedLines(model.rendered, model.lines, props.featurePoints)
})

function fpIntentLabel(intent: string): string {
  const suffix = intentLabelKeyOf(intent)
  return suffix ? t(`knowledge.blueprints.spec.${suffix}`) : intent
}

/** 渲染文本上的可见样式（记号已删除，只剩 dim / bold / code）。 */
const INLINE_STYLE_CLS: Partial<Record<InlineStyleKind, string>> = {
  dim: 'text-muted-foreground/70',
  bold: 'font-semibold text-foreground',
  code: 'rounded bg-muted/70 px-1 font-mono text-[12px]',
}

/** 任务框替代物（iconify 元素，无文本节点）。 */
const GLYPH_CLS: Record<string, string> = {
  'taskbox': 'icon-[lucide--square] mr-1 translate-y-[2px] text-[14px] text-muted-foreground/50',
  'taskbox-checked': 'icon-[lucide--square-check-big] mr-1 translate-y-[2px] text-[14px] text-primary/70',
}

// 标题两档 16/15px、正文 14px（§14：Heading 档不与 Body 同号，M-6）。
const LINE_CLS: Record<MarkdownLineKind, string> = {
  h1: 'mt-4 first:mt-0 text-base font-semibold leading-6 text-foreground',
  h2: 'mt-4 first:mt-0 text-base font-semibold leading-6 text-foreground',
  h3: 'mt-3 first:mt-0 text-[15px] font-semibold leading-6 text-foreground',
  h4: 'mt-3 first:mt-0 text-[15px] font-semibold leading-6 text-foreground',
  task: '',
  bullet: 'before:mr-2 before:inline-block before:size-1 before:translate-y-[-3px] before:rounded-full before:bg-muted-foreground/60 before:content-[\'\']',
  ordered: '',
  blank: 'h-2',
  plain: '',
}

interface RichAtom extends RenderSegment {
  styleCls: string
  /** 原子前插入的视觉替代物（任务框删除点）。 */
  glyphBefore: string
}

interface RichLine {
  meta: MarkdownLineMeta
  atoms: RichAtom[]
}

/** 缩进用 padding 承载（前导空格在 normal white-space 下折叠）。 */
function lineIndentStyle(meta: MarkdownLineMeta): Record<string, string> {
  if (meta.kind !== 'task' && meta.kind !== 'bullet' && meta.kind !== 'ordered')
    return {}
  return { paddingLeft: `${8 + meta.depth * 16}px` }
}

/**
 * 渲染空间的原子切分：批注（映射后）∪ 行 ∪ 样式 ∪ 替代物插入点。
 * 批注合法性仍按**源坐标**判（`isValidAnchor` + 越界整块降级逻辑不变），
 * 合法者映射到渲染坐标；完全落在被删记号里的（映射后空区间）不渲染 mark。
 */
const richLines = computed<RichLine[]>(() => {
  const model = renderModel.value
  if (!model || !model.rendered)
    return []

  const mappedRanges = ranges.value
    .filter(range => isValidAnchor(range, text.value.length))
    .map(range => ({
      threadId: range.threadId,
      start: model.toRendered(range.start),
      end: model.toRendered(range.end),
    }))
    .filter(range => range.start < range.end)

  const renderedSegments = sliceBlockText(model.rendered, mappedRanges)
  const segRanges: Array<{ start: number, end: number, threadIds: string[] }> = []
  let pos = 0
  for (const segment of renderedSegments) {
    segRanges.push({ start: pos, end: pos + segment.text.length, threadIds: segment.threadIds })
    pos += segment.text.length
  }

  const cuts = new Set<number>([0, model.rendered.length])
  for (const range of segRanges) {
    cuts.add(range.start)
    cuts.add(range.end)
  }
  for (const line of model.lines) {
    cuts.add(line.start)
    cuts.add(line.end)
  }
  for (const style of model.styles) {
    cuts.add(style.start)
    cuts.add(style.end)
  }
  for (const glyph of model.glyphs)
    cuts.add(glyph.rendOffset)
  const sorted = [...cuts].sort((a, b) => a - b)

  const glyphAt = new Map<number, string>()
  for (const glyph of model.glyphs)
    glyphAt.set(glyph.rendOffset, glyph.glyph)

  const lines: RichLine[] = model.lines.map(meta => ({ meta, atoms: [] }))
  let lineIdx = 0
  for (let i = 0; i < sorted.length - 1; i++) {
    const from = sorted[i]
    const to = sorted[i + 1]
    if (from >= to)
      continue
    while (lineIdx < lines.length - 1 && from >= lines[lineIdx].meta.end)
      lineIdx += 1
    const segment = segRanges.find(range => range.start <= from && range.end >= to)
    const style = model.styles.find(range => range.start <= from && range.end >= to)
    const base = decorate({
      text: model.rendered.slice(from, to),
      threadIds: segment?.threadIds ?? [],
    })
    lines[lineIdx].atoms.push({
      ...base,
      styleCls: (style && INLINE_STYLE_CLS[style.style]) || '',
      glyphBefore: glyphAt.get(from) ?? '',
    })
  }
  return lines
})

/**
 * 按 `\n` 把切分段还原成行。
 *
 * ⭐ `list` 的 offset 坐标系是「条目间用 `\n` 连接」的**扁平串**（后端 `_block_text` 用
 * `"\n".join`）⇒ 切分必须在扁平串上做，再按 `\n` 还原成 `<li>`，一个 `<li>` 内可含多个
 * 切分段。⛔ 不按条目各自从 0 计 offset。`pseudocode` 的行号列同理。
 */
const lines = computed<RenderSegment[][]>(() => {
  if (!text.value)
    return []
  const result: TextSegment[][] = [[]]
  for (const segment of segments.value) {
    const parts = segment.text.split('\n')
    parts.forEach((part, index) => {
      if (index > 0)
        result.push([])
      if (part.length > 0)
        result[result.length - 1].push({ text: part, threadIds: segment.threadIds })
    })
  }
  return result.map(line => line.map(decorate))
})

const tableRows = computed<string[][]>(() =>
  (Array.isArray(props.block.rows) ? props.block.rows : []).map(row =>
    Array.isArray(row) ? row.map(cell => String(cell ?? '')) : [],
  ),
)
const tableHead = computed(() => tableRows.value[0] ?? [])
const tableBody = computed(() => tableRows.value.slice(1))

const codeLanguage = computed(() => props.block.code?.language ?? '')

/** 块底 citation chip 行：⛔ 过滤掉池中取不到的 id，不渲染 `undefined`。 */
const blockCitations = computed<Citation[]>(() =>
  (props.block.citations ?? [])
    .map(id => props.citations?.[id])
    .filter((citation): citation is Citation => Boolean(citation)),
)

const copied = ref(false)

async function copySource(): Promise<void> {
  try {
    await navigator.clipboard?.writeText(text.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 1500)
  }
  catch {
    // 复制失败不反噬渲染（无剪贴板权限 / 非安全上下文）。
  }
}

function onSegmentActivate(segment: RenderSegment): void {
  if (segment.topThreadId)
    emit('thread-click', segment.topThreadId, segment.threadIds)
}

/** 整块色条角标：点击派发**优先级最高**那条，第二参数给出全量供上层弹选择器。 */
function onDegradedActivate(): void {
  const top = pickTopThread(degradedThreads.value)
  if (top)
    emit('thread-click', top.thread_id, degradedThreads.value.map(thread => thread.thread_id))
}
</script>

<template>
  <div
    :id="`blk-${block.block_id}`"
    :data-block-id="block.block_id"
    :data-block-type="block.type"
    data-testid="blueprint-block"
    class="relative py-1"
    :class="isDegraded ? ['border-l-2', 'pl-3', degradedClass] : []"
  >
    <!-- 越界 / table / mermaid 的整块降级角标：⚠️ 这些线程仍按 status 归组，⛔ 不进失锚组 -->
    <button
      v-if="isDegraded"
      type="button"
      data-testid="blueprint-block-degraded"
      :class="MARK_BASE_CLASS"
      class="absolute right-0 top-0 inline-flex items-center gap-0.5 px-1 text-[11px] text-muted-foreground hover:text-foreground"
      :title="t('knowledge.blueprints.annotation.degraded')"
      :aria-label="t('knowledge.blueprints.annotation.degraded')"
      @click="onDegradedActivate"
    >
      <span class="icon-[lucide--message-square-dot] text-[12px]" aria-hidden="true" />
      {{ degradedThreads.length }}
    </button>

    <!-- ⓪ paragraph 的 markdown 预览分支：DOM 只放**渲染文本**（## / ** / - [ ] 已删除），
         批注锚点经源↔渲染映射切 mark，选区由 BlockList 映射回源坐标（同一映射，同源实现）。 -->
    <div
      v-if="renderModel"
      data-testid="blueprint-markdown-lite"
      class="text-sm leading-relaxed"
    >
      <div
        v-for="(line, li) in richLines"
        :key="li"
        :class="LINE_CLS[line.meta.kind]"
        :style="lineIndentStyle(line.meta)"
        :data-md-line="line.meta.kind"
      >
        <template v-for="(seg, i) in line.atoms" :key="i">
          <!-- 任务框替代物：iconify 元素无文本节点，不污染选区坐标系 -->
          <span
            v-if="seg.glyphBefore"
            :class="GLYPH_CLS[seg.glyphBefore]"
            data-testid="blueprint-md-taskbox"
            aria-hidden="true"
          />
          <mark
            v-if="seg.mark"
            :data-thread-id="seg.topThreadId"
            :data-severity="seg.severity"
            :data-thread-status="seg.status"
            :class="[seg.cls, seg.styleCls]"
            role="button"
            tabindex="0"
            :aria-label="seg.label"
            :title="seg.label"
            data-testid="blueprint-annotation-mark"
            @click="onSegmentActivate(seg)"
            @keydown.enter.prevent="onSegmentActivate(seg)"
            @keydown.space.prevent="onSegmentActivate(seg)"
          >{{ seg.text }}</mark>
          <span v-else :class="seg.styleCls">{{ seg.text }}</span>
        </template>
        <!-- 功能点内联标签：零文本节点（文字走伪元素），承载 fp-<id> 跳转锚点。
             不可选中、不参与选区坐标系（与任务框替代物同款纪律）。 -->
        <span
          v-if="fpTagByLineStart.get(line.meta.start)"
          :id="`fp-${fpTagByLineStart.get(line.meta.start)!.pointId}`"
          class="bp-fp-tag scroll-mt-24"
          :data-fp-id="fpTagByLineStart.get(line.meta.start)!.pointId"
          :data-fp-intent="fpTagByLineStart.get(line.meta.start)!.intent"
          :data-fp-intent-label="fpIntentLabel(fpTagByLineStart.get(line.meta.start)!.intent)"
          :data-feature-point-id="fpTagByLineStart.get(line.meta.start)!.pointId"
          data-testid="blueprint-feature-point"
          role="note"
          :aria-label="`${fpTagByLineStart.get(line.meta.start)!.pointId} ${fpIntentLabel(fpTagByLineStart.get(line.meta.start)!.intent)}`"
        />
      </div>
    </div>

    <!-- ① paragraph。`whitespace-pre-line` 保住块内换行：机械 intake 可能把整段
         多行原文塞进一个 paragraph 块（如 requirement_spec.goal），默认 HTML 折叠
         换行会渲染成一面无结构的文字墙。只影响展示，不改文本内容，批注 offset 坐标系不受影响。 -->
    <p v-else-if="block.type === 'paragraph'" class="text-sm leading-relaxed whitespace-pre-line">
      <template v-for="(seg, i) in paragraphSegments" :key="i">
        <mark
          v-if="seg.mark"
          :data-thread-id="seg.topThreadId"
          :data-severity="seg.severity"
          :data-thread-status="seg.status"
          :class="seg.cls"
          role="button"
          tabindex="0"
          :aria-label="seg.label"
          :title="seg.label"
          data-testid="blueprint-annotation-mark"
          @click="onSegmentActivate(seg)"
          @keydown.enter.prevent="onSegmentActivate(seg)"
          @keydown.space.prevent="onSegmentActivate(seg)"
        >{{ seg.text }}</mark>
        <span v-else>{{ seg.text }}</span>
      </template>
    </p>

    <!-- ② list：切分在「条目 \n 连接」的扁平串上做，再还原成 <li> -->
    <ul v-else-if="block.type === 'list'" class="list-disc pl-5 space-y-1 text-sm">
      <li v-for="(line, i) in lines" :key="i">
        <template v-for="(seg, j) in line" :key="j">
          <mark
            v-if="seg.mark"
            :data-thread-id="seg.topThreadId"
            :data-severity="seg.severity"
            :data-thread-status="seg.status"
            :class="seg.cls"
            role="button"
            tabindex="0"
            :aria-label="seg.label"
            :title="seg.label"
            data-testid="blueprint-annotation-mark"
            @click="onSegmentActivate(seg)"
            @keydown.enter.prevent="onSegmentActivate(seg)"
            @keydown.space.prevent="onSegmentActivate(seg)"
          >{{ seg.text }}</mark>
          <span v-else>{{ seg.text }}</span>
        </template>
      </li>
    </ul>

    <!-- ③ table：语义 <table>，⛔ 不做字符级划线（坐标系无法映射到单元格） -->
    <div v-else-if="block.type === 'table'" class="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead v-for="(cell, i) in tableHead" :key="i" scope="col">
              {{ cell }}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="(row, i) in tableBody" :key="i">
            <TableCell v-for="(cell, j) in row" :key="j">
              {{ cell }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <!-- ④ pseudocode：语言徽标 + 复制 + 行号列；⛔ 不引语法高亮引擎（伪代码非真实语言） -->
    <div v-else-if="block.type === 'pseudocode'" class="rounded-md border border-border/50 bg-muted/20">
      <div class="flex items-center justify-between border-b border-border/40 px-2.5 py-1">
        <span class="text-[11px] text-muted-foreground">
          {{ codeLanguage ? t('knowledge.blueprints.block.language', { name: codeLanguage }) : '' }}
        </span>
        <button
          type="button"
          class="text-[11px] text-muted-foreground hover:text-primary"
          @click="copySource"
        >
          {{ copied ? t('knowledge.blueprints.block.copied') : t('knowledge.blueprints.block.copy') }}
        </button>
      </div>
      <div class="overflow-x-auto">
        <div v-for="(line, i) in lines" :key="i" class="flex items-start">
          <span class="select-none px-2 text-right font-mono text-xs leading-6 text-muted-foreground/60 min-w-[2.5rem]">{{ i + 1 }}</span>
          <pre class="flex-1 font-mono text-xs leading-6 whitespace-pre-wrap pr-3"><template v-for="(seg, j) in line" :key="j"><mark v-if="seg.mark" :data-thread-id="seg.topThreadId" :data-severity="seg.severity" :data-thread-status="seg.status" :class="seg.cls" role="button" tabindex="0" :aria-label="seg.label" :title="seg.label" data-testid="blueprint-annotation-mark" @click="onSegmentActivate(seg)" @keydown.enter.prevent="onSegmentActivate(seg)" @keydown.space.prevent="onSegmentActivate(seg)">{{ seg.text }}</mark><span v-else>{{ seg.text }}</span></template></pre>
        </div>
      </div>
    </div>

    <!-- ⑤ mermaid：预览弹层内退化为源码；空源码由调用方 v-if 判掉（组件自己不提示） -->
    <template v-else-if="block.type === 'mermaid'">
      <pre v-if="plainMermaid" class="font-mono text-xs leading-6 whitespace-pre-wrap rounded-md border border-border/50 bg-muted/20 p-3">{{ text }}</pre>
      <MermaidDiagram v-else-if="text.trim()" :code="text" />
      <p v-else class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.block.diagramUnavailable') }}
      </p>
    </template>

    <!-- citation chip 行 -->
    <div v-if="blockCitations.length" class="mt-1.5 flex flex-wrap items-center gap-1">
      <BlueprintCitationChip
        v-for="(citation, i) in blockCitations"
        :key="citation.citation_id"
        :citation="citation"
        :index="i + 1"
        @click="emit('citation-click', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
/*
 * 功能点内联标签（quick-260806）：文字**只**经 `content: attr(...)` 伪元素渲染 ——
 * 元素零文本节点，`collectTextNodes` 走不到它，批注选区的扁平坐标系不受污染。
 * 配色对齐 Badge 三档：greenfield→success(emerald) / brownfield→info(teal) / fix→warning(amber)。
 */
.bp-fp-tag {
  display: inline-flex;
  margin-left: 8px;
  vertical-align: 1px;
  user-select: none;
  white-space: nowrap;
}

.bp-fp-tag::before {
  content: attr(data-fp-id);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  line-height: 16px;
  padding: 0 5px;
  border: 1px solid var(--color-border);
  border-right: none;
  border-radius: 5px 0 0 5px;
  color: var(--color-muted-foreground);
  background: var(--color-background);
}

.bp-fp-tag::after {
  content: attr(data-fp-intent-label);
  font-size: 10px;
  line-height: 16px;
  padding: 0 5px;
  border: 1px solid var(--color-border);
  border-radius: 0 5px 5px 0;
  color: var(--color-muted-foreground);
  background: var(--color-muted);
}

.bp-fp-tag[data-fp-intent='greenfield']::after {
  color: var(--color-success-emphasis);
  background: color-mix(in srgb, var(--color-success) 10%, transparent);
  border-color: color-mix(in srgb, var(--color-success) 25%, transparent);
}

.bp-fp-tag[data-fp-intent='brownfield']::after {
  color: var(--color-primary-600);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  border-color: color-mix(in srgb, var(--color-primary) 25%, transparent);
}

.bp-fp-tag[data-fp-intent='fix']::after {
  color: var(--color-warning-emphasis);
  background: color-mix(in srgb, var(--color-warning) 12%, transparent);
  border-color: color-mix(in srgb, var(--color-warning) 30%, transparent);
}
</style>
