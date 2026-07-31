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
import type { BlueprintRequirementSpec, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import BlueprintBlockList from '../BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  spec?: BlueprintRequirementSpec | null
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  spec: null,
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

/** `intent` 三档 → 徽标 variant（⛔ 不发明第四档：未知值退 `outline`）。 */
const INTENT_VARIANT: Record<string, 'success' | 'info' | 'warning'> = {
  greenfield: 'success',
  brownfield: 'info',
  fix: 'warning',
}

const goalBlocks = computed(() => props.spec?.goal ?? [])
const backgroundBlocks = computed(() => props.spec?.background ?? [])
const featurePoints = computed(() => props.spec?.feature_points ?? [])

const isEmpty = computed(
  () => !goalBlocks.value.length && !backgroundBlocks.value.length && !featurePoints.value.length,
)

function intentVariant(intent: string | undefined): 'success' | 'info' | 'warning' | 'outline' {
  return INTENT_VARIANT[intent ?? ''] ?? 'outline'
}

/** `intent` 三档 → 中文名；未知值回落 schema 原样 token（⛔ 不发明第四档文案）。 */
const INTENT_LABEL_KEY: Record<string, string> = {
  greenfield: 'intentGreenfield',
  brownfield: 'intentBrownfield',
  fix: 'intentFix',
}

function intentLabel(intent: string | undefined): string {
  const suffix = INTENT_LABEL_KEY[intent ?? '']
  return suffix ? t(`knowledge.blueprints.spec.${suffix}`) : String(intent ?? '')
}

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
      <div v-if="goalBlocks.length" data-field="goal">
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.section.goal') }}
        </p>
        <BlueprintBlockList
          :blocks="goalBlocks"
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
      </div>

      <div v-if="backgroundBlocks.length" data-field="background">
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.section.background') }}
        </p>
        <BlueprintBlockList
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

      <div v-if="featurePoints.length" class="space-y-3" data-field="feature-points">
        <div
          v-for="point in featurePoints"
          :id="`fp-${point.id}`"
          :key="point.id"
          class="card p-4 space-y-2"
          data-testid="blueprint-feature-point"
          :data-feature-point-id="point.id"
        >
          <div class="flex items-start gap-2">
            <span class="font-mono text-[11px] text-muted-foreground shrink-0 mt-0.5">{{ point.id }}</span>
            <h4 class="text-sm font-semibold flex-1 min-w-0">
              {{ point.title }}
            </h4>
            <Badge :variant="intentVariant(point.intent)" :data-intent="point.intent">
              {{ intentLabel(point.intent) }}
            </Badge>
          </div>

          <BlueprintBlockList
            v-if="point.description?.length"
            :blocks="point.description"
            :section-path="`requirement_spec.feature_points[${point.id}].description`"
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
      </div>
    </template>
  </div>
</template>
