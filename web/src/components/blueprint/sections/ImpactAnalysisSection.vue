<script setup lang="ts">
/**
 * 影响范围段（Phase 115-05，UI-SPEC §6.1 段 5）。
 *
 * **职责**：薄壳 —— 有数据渲染 `ImpactMatrixTable`，无数据出 `CompactEmptyState`；
 * blockCtx 五个 prop 原样透传，⛔ 段组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * **分工边界（P-4）**：`<section id="impact_analysis">` 容器与导航项由页面无条件渲染，
 * 本组件只决定段内出不出内容。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type { BlueprintImpactAnalysis, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import ImpactMatrixTable from '../ImpactMatrixTable.vue'

const props = withDefaults(defineProps<{
  impact?: BlueprintImpactAnalysis | null
  repoNames?: Record<string, string>
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  impact: null,
  repoNames: () => ({}),
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

const isEmpty = computed(() => {
  const impact = props.impact
  if (!impact)
    return true
  return !(impact.business_impact?.length
    || impact.affected_features?.length
    || impact.regression_scope?.length
    || impact.compat_risks?.length
    || impact.rollback_plan?.length
    || (Array.isArray(impact.data_migrations) && impact.data_migrations.length))
})

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-impact-analysis">
    <CompactEmptyState
      v-if="isEmpty"
      icon="lucide--alert-triangle"
      :title="t('knowledge.blueprints.impact.empty')"
    />

    <ImpactMatrixTable
      v-else
      :impact="impact"
      :repo-names="repoNames"
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
</template>
