<script setup lang="ts">
/**
 * 需求规格段（Phase 115-05，UI-SPEC §6.1 段 0）。
 *
 * **职责**：把 `content.requirement_spec` 排版成「目标 / 背景 / 功能点清单」三块；
 * 所有 Block[] 一律交给 `BlueprintBlockList`，⛔ 段组件内不自行处理批注与引用
 * （UI-SPEC §13.3：批注层的唯一实现点是 `BlueprintBlock.vue`）。
 *
 * **分工边界（P-4，⛔ 不得越界）**：`<section id="requirement_spec">` 容器与左栏导航项由
 * 页面（115-06）**无条件渲染** —— `AnchorNavLayout` 的 IntersectionObserver 只在 mount 时
 * 注册，任何等数据到位才渲染容器的段都永远观察不到，症状是「点击跳转正常、左栏高亮不动」，
 * 人工走查逮不住。本组件只决定**段内出不出内容**。
 *
 * **跨段跳转的目标锚点**：功能点卡挂 `id="fp-<功能点 id>"`，供现状分析段与实现概述段的
 * `goto-anchor('fp-<id>')` 命中（滚动与 88px 偏移由页面统一处理）。
 *
 * ⚠️ **i18n 缺口（本 plan 按 §13.2 回报而不自补，见 115-05-SUMMARY §i18n）**：
 * `goal` / `background` 两个小标题与 `intent` 三档中文名在 `knowledge.blueprints.*` 里没有键。
 * 降级：两块不渲染文字小标题，身份由 `data-field` 承载；`intent` 徽标渲染 schema 原样 token
 * （颜色由 `variant` 承载，语义不丢），补键后只需换一处 `t()` 调用，无结构改动。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type {
  BlueprintFeaturePoint,
  BlueprintRequirementSpec,
  BlueprintThreadDetail,
  Citation,
} from '~/types/blueprint'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { blockText } from '~/utils/blueprintBlocks'
import {
  cleanFeaturePointTitle,
  intentLabelKeyOf,
  intentVariantOf,
  matchFeaturePointsToRenderedLines,
} from '~/utils/blueprintFeaturePoints'
import { buildMarkdownRender, isMarkdownishText } from '~/utils/blueprintMarkdownLite'
import BlueprintBlockList from '../BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  spec?: BlueprintRequirementSpec | null
  /**
   * 展开需求正文的外部信号（页面每次跳 `fp-*` 锚点就 +1）。
   *
   * 折叠是 CSS 裁切，被裁掉的功能点标签**仍在 DOM 里但不可见**，而页面的
   * `scrollToDom` 靠 `getBoundingClientRect()` 量位置 —— 不先展开就会滚到一个
   * 看不见的坐标。收到信号只**单向展开**（不回收），用户之后仍可自己收起。
   */
  expandGoalSignal?: number
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  spec: null,
  expandGoalSignal: 0,
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
})

const emit = defineEmits<{
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

const goalBlocks = computed(() => props.spec?.goal ?? [])
const backgroundBlocks = computed(() => props.spec?.background ?? [])
const featurePoints = computed(() => props.spec?.feature_points ?? [])

const isEmpty = computed(
  () => !goalBlocks.value.length && !backgroundBlocks.value.length && !featurePoints.value.length,
)

// ── 需求正文折叠（quick-260819：后端不再截字，长正文由这里收起）──────────────────
//
// ⛔ **不裁文本**：`ApiContractCard` 那种「JS 按行 slice 后再渲染」的折叠口径在这里
// 不能用 —— goal 正文承载批注划线，`BlueprintBlock` 的 mark 分段按**文本 offset**
// 定位，少喂一个字后面所有划线就全错位，功能点内联标签也会跟着丢。
// 所以折叠一律走 **CSS max-height 裁切**：整段正文恒在 DOM 里（offset 坐标系不动），
// 只是视觉上被蒙层盖住。用户点「展开全部」即解除 max-height。

/** 正文超过该字数才提供折叠（≈ 折叠高度装得下的量，短正文不该出现无意义的按钮）。 */
const GOAL_FOLD_MIN_CHARS = 2400

const goalExpanded = ref(false)

const goalText = computed(() => goalBlocks.value.map(block => blockText(block)).join('\n'))

const goalFoldable = computed(() => goalText.value.length > GOAL_FOLD_MIN_CHARS)

/** 折叠中 = 够长且用户没展开。蒙层与按钮共用这一个判据。 */
const goalCollapsed = computed(() => goalFoldable.value && !goalExpanded.value)

watch(() => props.expandGoalSignal, () => {
  goalExpanded.value = true
})

// ── 功能点内联标签 + 兜底索引（quick-260806：功能点分散进目标正文）────────────────
//
// goal 正文本就完整包含各模块与验收细节 ⇒ 功能点标签**内联到正文对应行的行尾**
// （`BlueprintBlock` 的零文本节点标签，承载 `fp-<id>` 锚点），不再在下方整表聚合。
// 只有**没能在正文里定位到标题行**的功能点才落进下方兜底索引（锚点不能丢：现状分析/
// 实现概述/澄清向导的 goto-anchor 都指向 `fp-<id>`）。

/** 已内联进 goal 正文的功能点 id（与 BlueprintBlock 同一匹配器，输入同源 ⇒ 结果一致）。 */
const inlineTaggedIds = computed(() => {
  const ids = new Set<string>()
  for (const block of goalBlocks.value) {
    if (block?.type !== 'paragraph')
      continue
    const flat = blockText(block)
    if (!isMarkdownishText(flat))
      continue
    const model = buildMarkdownRender(flat)
    for (const tag of matchFeaturePointsToRenderedLines(
      model.rendered,
      model.lines,
      featurePoints.value,
    ).values())
      ids.add(tag.pointId)
  }
  return ids
})

/** 兜底索引：只列没内联进正文的点（通常为空 ⇒ 整块不渲染）。 */
const unmatchedPoints = computed(() =>
  featurePoints.value.filter(point => !inlineTaggedIds.value.has(point.id)),
)

/** intent 计数摘要（按 schema 三档出现顺序稳定输出，count 为 0 的档不出现）。 */
const intentSummary = computed(() => {
  const counts = new Map<string, number>()
  for (const point of featurePoints.value)
    counts.set(point.intent, (counts.get(point.intent) ?? 0) + 1)
  return ['greenfield', 'brownfield', 'fix']
    .filter(intent => counts.has(intent))
    .map(intent => ({ intent, count: counts.get(intent)! }))
})

/**
 * 功能点所属模块标签：取 description 首个非空文本行，且仅当它以「模块」开头才视为
 * 模块标签（机械拆解器把「模块 N：xxx」放进 description 首块）。判不出归入无标签组，
 * ⛔ 不把任意长描述当组头。
 */
function moduleLabelOf(point: BlueprintFeaturePoint): string {
  for (const block of point.description ?? []) {
    // `BlueprintBlock.text` 是 `unknown`（块形态由 kind 决定，schema 不收窄）⇒ 两种形态都收。
    const raw = Array.isArray(block?.text) ? block.text.join(' ') : String(block?.text ?? '')
    const line = raw.trim()
    if (line)
      return line.startsWith('模块') ? line : ''
  }
  return ''
}

/** 兜底索引按模块归组（保持首次出现顺序）；无标签组 label 为空串、组头不渲染。 */
const moduleGroups = computed(() => {
  const groups: Array<{ label: string, points: typeof featurePoints.value }> = []
  const byLabel = new Map<string, { label: string, points: typeof featurePoints.value }>()
  for (const point of unmatchedPoints.value) {
    const label = moduleLabelOf(point)
    let group = byLabel.get(label)
    if (!group) {
      group = { label, points: [] }
      byLabel.set(label, group)
      groups.push(group)
    }
    group.points.push(point)
  }
  return groups
})

/** `intent` 口径（variant / 中文名 / 标题记号剥离）统一走 `utils/blueprintFeaturePoints`。 */
const intentVariant = intentVariantOf

function intentLabel(intent: string | undefined): string {
  const suffix = intentLabelKeyOf(intent)
  return suffix ? t(`knowledge.blueprints.spec.${suffix}`) : String(intent ?? '')
}

const cleanTitle = cleanFeaturePointTitle

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-requirement-spec" class="space-y-4">
    <CompactEmptyState
      v-if="isEmpty"
      icon="lucide--file-text"
      :title="t('knowledge.blueprints.sectionEmpty', { name: t('knowledge.blueprints.section.requirementSpec') })"
    />

    <template v-else>
      <!-- ⭐ quick-260806 视觉整改：目标正文与功能点状态**合并进同一张卡** ——
           goal 里已含各模块与验收细节，功能点不再逐个铺大卡重复展示，收敛为
           「摘要头计数 + 按模块归组的单行状态索引」。 -->
      <div class="card overflow-hidden" data-field="requirement-spec-card">
        <!-- 摘要头：本需求共几个功能点、各状态几个，一眼建立与下方索引的关联 -->
        <header
          v-if="featurePoints.length"
          class="flex flex-wrap items-center gap-2 border-b border-border/70 bg-muted/20 px-4 py-2.5"
          data-testid="blueprint-spec-summary"
        >
          <span class="text-sm font-medium">
            {{ t('knowledge.blueprints.spec.pointsTotal', { n: featurePoints.length }) }}
          </span>
          <Badge
            v-for="row in intentSummary"
            :key="row.intent"
            :variant="intentVariant(row.intent)"
            :data-intent="row.intent"
          >
            {{ intentLabel(row.intent) }} {{ row.count }}
          </Badge>
        </header>

        <!-- ⭐ 长文阅读面控行长：正文限 52rem（≈52 汉字/行）。max-w 不改文本节点，
             批注 offset 坐标系不受影响。 -->
        <div v-if="goalBlocks.length" data-field="goal" class="px-4 py-3.5">
          <!-- ⭐ 折叠容器：`max-h` + `overflow-hidden` 纯 CSS 裁切，正文**全量**留在 DOM
               里（批注 offset 与内联功能点标签都不受影响，见 script 段说明）。 -->
          <div
            class="relative"
            :class="goalCollapsed ? 'max-h-160 overflow-hidden' : ''"
            data-testid="blueprint-spec-goal-fold"
            :data-collapsed="goalCollapsed ? 'true' : 'false'"
          >
            <!-- ⭐ feature-points 只传给 goal：功能点标签内联到正文对应标题行的行尾 -->
            <BlueprintBlockList
              class="max-w-208"
              :blocks="goalBlocks"
              :feature-points="featurePoints"
              section-path="requirement_spec.goal"
              :threads="threads"
              :citations="citations"
              :readonly="readonly"
              :active-thread-id="activeThreadId"
              :show-closed="showClosed"
              @thread-click="forwardThread"
              @citation-click="emit('citation-click', $event)"
              @selection-comment="emit('selection-comment', $event)"
              @cross-block-selection="emit('cross-block-selection')"
            />
            <!-- 渐变蒙层：`pointer-events-none` —— 绝不能挡住划线选区与 mark 点击 -->
            <div
              v-if="goalCollapsed"
              class="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-card via-card/85 to-transparent"
              aria-hidden="true"
            />
          </div>
          <button
            v-if="goalFoldable"
            type="button"
            class="mt-1 text-xs text-primary hover:underline"
            data-testid="blueprint-spec-goal-toggle"
            :aria-expanded="goalExpanded"
            @click="goalExpanded = !goalExpanded"
          >
            {{ goalExpanded
              ? t('knowledge.blueprints.block.collapse')
              : t('knowledge.blueprints.block.expandAll') }}
          </button>
        </div>

        <div v-if="backgroundBlocks.length" data-field="background" class="border-t border-border/70 px-4 py-3.5">
          <p class="mb-1.5 text-xs font-medium text-muted-foreground">
            {{ t('knowledge.blueprints.section.background') }}
          </p>
          <BlueprintBlockList
            class="max-w-208"
            :blocks="backgroundBlocks"
            section-path="requirement_spec.background"
            :threads="threads"
            :citations="citations"
            :readonly="readonly"
            :active-thread-id="activeThreadId"
            :show-closed="showClosed"
            @thread-click="forwardThread"
            @citation-click="emit('citation-click', $event)"
            @selection-comment="emit('selection-comment', $event)"
            @cross-block-selection="emit('cross-block-selection')"
          />
        </div>

        <!-- ⭐ 兜底索引：只列**没能内联进正文**的功能点（标题行在 goal 里定位失败的少数派；
             `fp-<id>` 锚点不能丢——跨段 goto-anchor 的落点）。全部内联成功时整块不渲染。 -->
        <div
          v-if="unmatchedPoints.length"
          class="border-t border-border/70 px-4 py-3.5"
          data-field="feature-points"
        >
          <p class="mb-2 text-xs font-medium text-muted-foreground">
            {{ t('knowledge.blueprints.spec.pointsIndexUnmatched') }}
          </p>
          <div class="space-y-3">
            <div v-for="group in moduleGroups" :key="group.label || '_ungrouped'">
              <p v-if="group.label" class="mb-1 text-xs font-semibold text-foreground/75">
                {{ group.label }}
              </p>
              <div class="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
                <div
                  v-for="point in group.points"
                  :id="`fp-${point.id}`"
                  :key="point.id"
                  class="flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1 scroll-mt-24 hover:bg-muted/40"
                  data-testid="blueprint-feature-point"
                  :data-feature-point-id="point.id"
                >
                  <span class="w-11 shrink-0 font-mono text-[11px] text-muted-foreground">{{ point.id }}</span>
                  <span class="min-w-0 flex-1 truncate text-sm" :title="cleanTitle(point.title)">
                    {{ cleanTitle(point.title) }}
                  </span>
                  <Badge :variant="intentVariant(point.intent)" :data-intent="point.intent" class="shrink-0">
                    {{ intentLabel(point.intent) }}
                  </Badge>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
