<script setup lang="ts">
/**
 * 实现概述段（Phase 115-05，UI-SPEC §6.1 段 3 / §6.5；quick-260806-fpx 三层连通整改）。
 *
 * **职责**：三层排版 —— `requirement_narrative`（Block[]）→ `modules[]`（卡片）→ `items[]`
 * （逐个 `ImplementationItemCard`）。所有 Block[] 一律交给 `BlueprintBlockList`，
 * ⛔ 段组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⭐ **三层是同一条链，不是三个并列列表**（quick-260806-fpx）：
 * 模块卡 = 「功能点 ← 模块 → 实现项」的枢纽。它挂 `id="mod-<模块 id>"` 锚点，向上用
 * `BlueprintFeaturePointChip` 连到需求规格的功能点，向下折叠列出**本模块的实现项**并可
 * 点击滚到对应卡；实现项卡反过来用模块 chip 跳回来。整改前这三层在界面上互不相连，
 * 读者要靠肉眼把 6 张模块卡和 54 张实现项卡对上，这是本段最贵的阅读成本。
 *
 * ⭐ **波次泳道条是纯客户端筛选**：状态存在本地 `ref`，⛔ 不写 URL、⛔ 不引 router
 * —— 它是阅读辅助而不是可分享的视图状态，写进 URL 会让「把链接发给同事」这件事带上
 * 一个别人不需要的筛选。
 *
 * ⭐ **筛选与跳转的冲突必须自解（T-fpx-01）**：波次筛选开启时，跳向被筛掉的实现项
 * （模块卡清单项、实现项卡的 `depends_on`）会滚到一个**没渲染的锚点**上 —— 症状是
 * 「点了没反应」，且只在筛选态复现。`onItemAnchor` 统一在 emit 前判断目标是否可见，
 * 不可见就先清筛选。⛔ 不要绕过它直接 emit `impl-*` 锚点。
 *
 * ⭐ **跨段跳转一律 emit 给页面**：⛔ 段内不自行调用任何滚动 API（88px 偏移常量归页面）。
 *
 * **分工边界（P-4）**：`<section id="implementation_overview">` 容器与导航项由页面无条件渲染。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type {
  BlueprintFeaturePoint,
  BlueprintImplementationItem,
  BlueprintImplementationOverview,
  BlueprintThreadDetail,
  Citation,
} from '~/types/blueprint'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { changeTypeMetaOf } from '~/utils/blueprintImplItems'
import BlueprintBlockList from '../BlueprintBlockList.vue'
import BlueprintFeaturePointChip from '../BlueprintFeaturePointChip.vue'
import ImplementationItemCard from '../ImplementationItemCard.vue'

const props = withDefaults(defineProps<{
  overview?: BlueprintImplementationOverview | null
  repoNames?: Record<string, string>
  /** 功能点索引（id → 完整功能点），供 chip 出悬浮预览；缺项只降级成「id 无标题」。 */
  featurePoints?: Record<string, BlueprintFeaturePoint>
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  overview: null,
  repoNames: () => ({}),
  featurePoints: () => ({}),
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

/** 模块 id → 本模块实现项（保持 `items[]` 原序；无 `module_id` 的项不归入任何模块）。 */
const itemsByModule = computed(() => {
  const map = new Map<string, BlueprintImplementationItem[]>()
  for (const item of items.value) {
    const key = String(item.module_id ?? '').trim()
    if (!key)
      continue
    const bucket = map.get(key)
    if (bucket)
      bucket.push(item)
    else map.set(key, [item])
  }
  return map
})

function moduleItemsOf(moduleId: string | undefined): BlueprintImplementationItem[] {
  return itemsByModule.value.get(String(moduleId ?? '').trim()) ?? []
}

function toggleWave(wave: number): void {
  activeWave.value = activeWave.value === wave ? null : wave
}

function repoLabel(repositoryId: string | undefined): string {
  if (!repositoryId)
    return ''
  return props.repoNames?.[repositoryId] || repositoryId
}

/**
 * ⭐ 跳实现项前先保证它可见：波次筛选把目标筛掉时锚点不存在，滚动静默失败。
 * 非 `impl-*` 锚点（功能点、模块）原样转发。
 */
function onItemAnchor(domId: string): void {
  if (activeWave.value !== null && domId.startsWith('impl-')) {
    const target = items.value.find(item => item.id === domId.slice('impl-'.length))
    if (target && target.wave !== activeWave.value)
      activeWave.value = null
  }
  emit('goto-anchor', domId)
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-implementation-overview" class="space-y-5">
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

      <!-- ⭐ 模块层：功能点 ← 模块 → 实现项 的枢纽 -->
      <section v-if="modules.length" data-field="modules" class="space-y-2.5">
        <!-- 子段标签走 `text-sm font-medium`：Heading 档（`text-base font-semibold`）归段标题
             与卡片标题，字段标签归 `text-xs`；这里插在两者之间，⛔ 不跟任何一档同形。 -->
        <h3 class="text-sm font-medium text-foreground">
          {{ t('knowledge.blueprints.impl.modulesTitle') }}
          <span class="ml-1 text-xs text-muted-foreground">{{ t('knowledge.blueprints.impl.modulesTotal', { n: modules.length }) }}</span>
        </h3>

        <div class="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
          <div
            v-for="(mod, modIndex) in modules"
            :id="mod.id ? `mod-${mod.id}` : undefined"
            :key="mod.id ?? modIndex"
            class="card flex flex-col scroll-mt-24"
            data-testid="blueprint-impl-module"
            :data-module-id="mod.id ?? ''"
          >
            <div class="flex items-start gap-2.5 border-b border-border/50 px-4 py-3">
              <span class="icon-[lucide--boxes] mt-0.5 shrink-0 text-primary" aria-hidden="true" />
              <div class="min-w-0 flex-1">
                <h4 class="text-base leading-snug font-semibold">
                  {{ mod.name || mod.id || '—' }}
                </h4>
                <p v-if="mod.id && mod.name" class="mt-0.5 font-mono text-[11px] text-muted-foreground">
                  {{ mod.id }}
                </p>
              </div>
              <Badge
                v-if="moduleItemsOf(mod.id).length"
                variant="secondary"
                class="shrink-0 tabular-nums"
              >
                {{ t('knowledge.blueprints.impl.itemCount', { n: moduleItemsOf(mod.id).length }) }}
              </Badge>
            </div>

            <div class="flex-1 space-y-3 p-4">
              <div v-if="mod.feature_point_ids?.length">
                <p class="mb-1.5 text-xs font-medium text-muted-foreground">
                  {{ t('knowledge.blueprints.impl.coveredFeaturePoints') }}
                </p>
                <div class="flex flex-wrap gap-1.5">
                  <BlueprintFeaturePointChip
                    v-for="fp in mod.feature_point_ids"
                    :key="fp"
                    :point-id="fp"
                    :point="featurePoints[fp] ?? null"
                    show-title
                    @goto-anchor="emit('goto-anchor', $event)"
                  />
                </div>
              </div>

              <div v-if="mod.repository_ids?.length" class="flex flex-wrap items-center gap-1.5">
                <span class="icon-[lucide--git-branch] shrink-0 text-muted-foreground" aria-hidden="true" />
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

            <!-- ⭐ 向下连到实现项：折叠清单，点一条滚到对应实现项卡 -->
            <Collapsible v-if="moduleItemsOf(mod.id).length">
              <CollapsibleTrigger
                class="group flex w-full items-center gap-1.5 border-t border-border/50 px-4 py-2.5 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/30 hover:text-foreground"
                data-testid="blueprint-module-items-trigger"
              >
                <span
                  class="icon-[lucide--chevron-right] shrink-0 transition-transform group-data-[state=open]:rotate-90"
                  aria-hidden="true"
                />
                {{ t('knowledge.blueprints.impl.moduleItemsToggle', { n: moduleItemsOf(mod.id).length }) }}
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ul class="divide-y divide-border/40 border-t border-border/40">
                  <li v-for="item in moduleItemsOf(mod.id)" :key="item.id">
                    <button
                      type="button"
                      class="flex w-full items-center gap-2 px-4 py-2 text-left text-xs transition-colors hover:bg-muted/40"
                      data-testid="blueprint-module-item-link"
                      :data-impl-id="item.id"
                      @click="onItemAnchor(`impl-${item.id}`)"
                    >
                      <span
                        :class="`icon-[${changeTypeMetaOf(item.change_type)?.icon ?? 'lucide--file-cog'}] shrink-0 text-muted-foreground`"
                        aria-hidden="true"
                      />
                      <span class="min-w-0 flex-1 truncate">{{ item.title }}</span>
                      <span
                        v-if="item.wave !== undefined"
                        class="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums"
                      >{{ t('knowledge.blueprints.impl.waveShort', { n: item.wave }) }}</span>
                    </button>
                  </li>
                </ul>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </div>
      </section>

      <section v-if="items.length" data-field="items" class="space-y-2.5">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h3 class="text-sm font-medium text-foreground">
            {{ t('knowledge.blueprints.impl.itemsTitle') }}
            <span class="ml-1 text-xs text-muted-foreground">
              {{ activeWave === null
                ? t('knowledge.blueprints.impl.itemsTotal', { n: items.length })
                : t('knowledge.blueprints.impl.itemsFiltered', { n: visibleItems.length, total: items.length }) }}
            </span>
          </h3>

          <!-- ⭐ 波次泳道条：纯客户端筛选，不改 URL；「全部」是显式复位（⛔ 不把复位
               只藏在「再点一次当前波次」这个不可见约定里） -->
          <div v-if="waves.length > 1" class="ml-auto flex flex-wrap items-center gap-1.5" data-testid="blueprint-wave-lane">
            <button
              type="button"
              class="rounded-lg border px-2.5 py-1 text-xs transition-colors"
              :class="activeWave === null ? 'border-primary/50 bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'"
              :aria-pressed="activeWave === null"
              data-testid="blueprint-wave-chip-all"
              @click="activeWave = null"
            >
              {{ t('knowledge.blueprints.impl.waveAll') }}
            </button>
            <button
              v-for="lane in waves"
              :key="lane.wave"
              type="button"
              class="rounded-lg border px-2.5 py-1 text-xs tabular-nums transition-colors"
              :class="activeWave === lane.wave ? 'border-primary/50 bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:border-primary/40 hover:text-foreground'"
              :aria-pressed="activeWave === lane.wave"
              data-testid="blueprint-wave-chip"
              :data-wave="lane.wave"
              @click="toggleWave(lane.wave)"
            >
              {{ t('knowledge.blueprints.impl.waveCount', { n: lane.wave, c: lane.count }) }}
            </button>
          </div>
        </div>

        <div class="space-y-4">
          <ImplementationItemCard
            v-for="item in visibleItems"
            :key="item.id"
            :item="item"
            :module-name="item.module_id ? moduleNames[item.module_id] ?? '' : ''"
            :repo-name="repoLabel(item.repository_id)"
            :feature-point="item.feature_point_id ? featurePoints[item.feature_point_id] ?? null : null"
            :threads="threads"
            :citations="citations"
            :readonly="readonly"
            :active-thread-id="activeThreadId"
            :show-closed="showClosed"
            @goto-anchor="onItemAnchor"
            @thread-click="forwardThread"
            @citation-click="emit('citation-click', $event)"
            @selection-comment="emit('selection-comment', $event)"
            @cross-block-selection="emit('cross-block-selection')"
          />
        </div>
      </section>
    </template>
  </div>
</template>
