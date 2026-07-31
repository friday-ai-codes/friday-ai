<script setup lang="ts">
/**
 * 实现概述段（Phase 115-05，UI-SPEC §6.1 段 3 / §6.5）。
 *
 * **职责**：三层排版 —— `requirement_narrative`（Block[]）→ `modules[]`（卡片）→ `items[]`
 * （逐个 `ImplementationItemCard`）。所有 Block[] 一律交给 `BlueprintBlockList`，
 * ⛔ 段组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⭐ **波次泳道条是纯客户端筛选**：状态存在本地 `ref`，⛔ 不写 URL、⛔ 不引 router
 * —— 它是阅读辅助而不是可分享的视图状态，写进 URL 会让「把链接发给同事」这件事带上
 * 一个别人不需要的筛选。再次点击同一波次即取消筛选。
 *
 * ⭐ **跨段跳转一律 emit 给页面**：模块卡的关联功能点 chip 点击 emit
 * `goto-anchor('fp-<功能点 id>')`，⛔ 段内不自行调用任何滚动 API（88px 偏移常量归页面）。
 *
 * **分工边界（P-4）**：`<section id="implementation_overview">` 容器与导航项由页面无条件渲染。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补）**：「需求叙事」「功能模块」两个小标题与波次泳道的
 * 「{n} 项」计量词无键 ⇒ 两块不渲染文字小标题（身份走 `data-field`），泳道条渲染
 * `wave {n}` + 计数徽标。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type {
  BlueprintImplementationOverview,
  BlueprintThreadDetail,
  Citation,
} from '~/types/blueprint'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import BlueprintBlockList from '../BlueprintBlockList.vue'
import ImplementationItemCard from '../ImplementationItemCard.vue'

const props = withDefaults(defineProps<{
  overview?: BlueprintImplementationOverview | null
  repoNames?: Record<string, string>
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  overview: null,
  repoNames: () => ({}),
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
})

const emit = defineEmits<{
  'goto-anchor': [domId: string]
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

/** ⭐ 纯客户端筛选态：`null` = 不筛选。 */
const activeWave = ref<number | null>(null)

const narrativeBlocks = computed(() => props.overview?.requirement_narrative ?? [])
const modules = computed(() => props.overview?.modules ?? [])
const items = computed(() => props.overview?.items ?? [])

const isEmpty = computed(() => !narrativeBlocks.value.length && !modules.value.length && !items.value.length)

/** 波次泳道：按 `wave` 升序聚合计数（缺 `wave` 的实现项不进泳道条，但始终参与渲染）。 */
const waves = computed(() => {
  const counter = new Map<number, number>()
  for (const item of items.value) {
    if (typeof item.wave === 'number' && Number.isFinite(item.wave))
      counter.set(item.wave, (counter.get(item.wave) ?? 0) + 1)
  }
  return [...counter.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([wave, count]) => ({ wave, count }))
})

const visibleItems = computed(() => {
  if (activeWave.value === null)
    return items.value
  return items.value.filter(item => item.wave === activeWave.value)
})

const moduleNames = computed(() => {
  const map: Record<string, string> = {}
  for (const mod of modules.value) {
    if (mod.id)
      map[mod.id] = mod.name ?? mod.id
  }
  return map
})

function toggleWave(wave: number): void {
  activeWave.value = activeWave.value === wave ? null : wave
}

function repoLabel(repositoryId: string | undefined): string {
  if (!repositoryId)
    return ''
  return props.repoNames?.[repositoryId] || repositoryId
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-implementation-overview" class="space-y-4">
    <CompactEmptyState
      v-if="isEmpty"
      icon="lucide--layers"
      :title="t('knowledge.blueprints.sectionEmpty', { name: t('knowledge.blueprints.section.implementationOverview') })"
    />

    <template v-else>
      <div v-if="narrativeBlocks.length" data-field="requirement-narrative">
        <BlueprintBlockList
          :blocks="narrativeBlocks"
          section-path="implementation_overview.requirement_narrative"
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

      <div v-if="modules.length" class="grid grid-cols-1 gap-4 lg:grid-cols-2" data-field="modules">
        <div
          v-for="(mod, modIndex) in modules"
          :key="mod.id ?? modIndex"
          class="card space-y-2 p-4"
          data-testid="blueprint-impl-module"
          :data-module-id="mod.id ?? ''"
        >
          <h4 class="text-sm font-semibold">
            {{ mod.name || mod.id || '—' }}
          </h4>

          <div v-if="mod.feature_point_ids?.length" class="flex flex-wrap gap-1">
            <button
              v-for="fp in mod.feature_point_ids"
              :key="fp"
              type="button"
              class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground hover:border-primary/40 hover:text-primary"
              data-testid="blueprint-feature-point-chip"
              @click="emit('goto-anchor', `fp-${fp}`)"
            >
              {{ fp }}
            </button>
          </div>

          <div v-if="mod.repository_ids?.length" class="flex flex-wrap gap-1">
            <span
              v-for="repositoryId in mod.repository_ids"
              :key="repositoryId"
              class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >{{ repoLabel(repositoryId) }}</span>
          </div>

          <BlueprintBlockList
            v-if="mod.narrative?.length"
            :blocks="mod.narrative"
            :section-path="`implementation_overview.modules[${mod.id ?? modIndex}].narrative`"
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

      <!-- ⭐ 波次泳道条：纯客户端筛选，不改 URL -->
      <div v-if="waves.length > 1" class="flex flex-wrap items-center gap-2" data-testid="blueprint-wave-lane">
        <button
          v-for="lane in waves"
          :key="lane.wave"
          type="button"
          class="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs transition-colors"
          :class="activeWave === lane.wave ? 'border-primary/50 bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/40'"
          :aria-pressed="activeWave === lane.wave"
          data-testid="blueprint-wave-chip"
          :data-wave="lane.wave"
          @click="toggleWave(lane.wave)"
        >
          <span class="font-mono">wave {{ lane.wave }}</span>
          <Badge variant="muted">
            {{ lane.count }}
          </Badge>
        </button>
      </div>

      <div v-if="items.length" class="space-y-4" data-field="items">
        <ImplementationItemCard
          v-for="item in visibleItems"
          :key="item.id"
          :item="item"
          :module-name="item.module_id ? moduleNames[item.module_id] ?? '' : ''"
          :repo-name="repoLabel(item.repository_id)"
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
  </div>
</template>
