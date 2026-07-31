<script setup lang="ts">
/**
 * 影响矩阵（Phase 115-05，UI-SPEC §6.7）。
 *
 * **职责**：五块 —— `business_impact` 置顶（业务语言优先）→ `affected_features` 矩阵表 →
 * `regression_scope` 紧凑清单 → `compat_risks` / `rollback_plan` → `data_migrations`。
 * 所有 Block[] 一律交给 `BlueprintBlockList`，⛔ 本组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⭐ **`reversible === false` 严格判等**：缺键的迁移条目**不加**「不可逆」徽标。用 falsy 判断
 * （`!item.reversible`）会把「没写这个键」误标成「不可逆」，把数据缺失伪装成风险结论（T-115-45）。
 *
 * ⭐ **窄屏（`< md`）降级为卡片堆叠，⛔ 不做横向滚动表**（UI-SPEC §6.7）：矩阵表在手机上横向
 * 滚动等于把「一眼看全影响面」这件事变成「一列一列擦」，而影响面恰恰是评审最需要整体扫视的一块。
 * 实现用 `hidden md:table` + `md:hidden` 双份结构。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补）**：「不可逆」无键 ⇒ 徽标渲染 schema 原样判据
 * `reversible=false`，身份由 `data-irreversible="true"` 承载；`kind` 五档与 `level` 三档的
 * 中文名有键（`impact.kind*` / `impact.level*`）已直接使用；`regression_scope` 的列头
 * （区域 / 理由）无键 ⇒ 该块改为「徽标 + 区域 + 理由」的行式呈现，不发明列头文案。
 */

import type { SelectionPayload } from './BlueprintBlockList.vue'
import type { BlueprintImpactAnalysis, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import BlueprintBlockList from './BlueprintBlockList.vue'

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

/** `affected_features[].kind` 五档。 */
const KIND_META: Record<string, { variant: 'warning' | 'info' | 'destructive' | 'muted', labelKey: string }> = {
  behavior_change: { variant: 'warning', labelKey: 'kindBehaviorChange' },
  perf: { variant: 'info', labelKey: 'kindPerf' },
  compat: { variant: 'warning', labelKey: 'kindCompat' },
  data: { variant: 'destructive', labelKey: 'kindData' },
  none: { variant: 'muted', labelKey: 'kindNone' },
}

/** `regression_scope[].level` 三档。 */
const LEVEL_META: Record<string, { variant: 'destructive' | 'warning' | 'muted', labelKey: string }> = {
  full: { variant: 'destructive', labelKey: 'levelFull' },
  smoke: { variant: 'warning', labelKey: 'levelSmoke' },
  none: { variant: 'muted', labelKey: 'levelNone' },
}

const businessImpactBlocks = computed(() => props.impact?.business_impact ?? [])
const affectedFeatures = computed(() => props.impact?.affected_features ?? [])
const regressionScope = computed(() => props.impact?.regression_scope ?? [])
const compatRiskBlocks = computed(() => props.impact?.compat_risks ?? [])
const rollbackBlocks = computed(() => props.impact?.rollback_plan ?? [])

/** `data_migrations` 条目形状零约束 ⇒ 逐键收窄；⭐ `reversible` 只认严格 `false`。 */
const dataMigrations = computed(() => {
  const list = props.impact?.data_migrations
  if (!Array.isArray(list))
    return []
  return list.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>
    const description = typeof item.description === 'string' && item.description ? item.description : '—'
    return {
      key: `${index}`,
      description,
      irreversible: item.reversible === false,
    }
  })
})

function kindMeta(kind: string) {
  return KIND_META[kind] ?? null
}

function levelMeta(level: string | undefined) {
  return LEVEL_META[level ?? ''] ?? null
}

function repoLabels(repositoryIds: string[] | undefined): string {
  if (!Array.isArray(repositoryIds) || !repositoryIds.length)
    return '—'
  return repositoryIds.map(id => props.repoNames?.[id] || id).join('、')
}

function citationLabels(citationIds: string[] | undefined): string[] {
  if (!Array.isArray(citationIds))
    return []
  return citationIds.filter(id => typeof id === 'string' && id)
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-impact-matrix" class="space-y-4">
    <!-- ① 业务影响置顶 -->
    <div v-if="businessImpactBlocks.length" data-field="business-impact" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.impact.businessImpact') }}
      </p>
      <BlueprintBlockList
        :blocks="businessImpactBlocks"
        section-path="impact_analysis.business_impact"
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

    <!-- ② 受影响功能矩阵：md 以上是语义表，窄屏改卡片堆叠（⛔ 不做横向滚动表） -->
    <div v-if="affectedFeatures.length" data-field="affected-features" class="space-y-2">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.impact.feature') }}
      </p>

      <Table class="hidden md:table">
        <TableHeader>
          <TableRow>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.impact.feature') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.tabPanel.filterRepository') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.impact.kind') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.flow.note') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.citation.open') }}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="(feature, index) in affectedFeatures"
            :key="`${feature.feature}-${index}`"
            data-testid="blueprint-impact-row"
          >
            <TableCell class="text-sm font-medium">
              {{ feature.feature }}
            </TableCell>
            <TableCell class="text-xs text-muted-foreground">
              {{ repoLabels(feature.repository_ids) }}
            </TableCell>
            <TableCell>
              <Badge v-if="kindMeta(feature.kind)" :variant="kindMeta(feature.kind)!.variant" :data-kind="feature.kind">
                {{ t(`knowledge.blueprints.impact.${kindMeta(feature.kind)!.labelKey}`) }}
              </Badge>
              <Badge v-else variant="outline" :data-kind="feature.kind">
                {{ feature.kind }}
              </Badge>
            </TableCell>
            <TableCell>
              <BlueprintBlockList
                v-if="feature.description?.length"
                :blocks="feature.description"
                :section-path="`impact_analysis.affected_features[${feature.feature}].description`"
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
              <span v-else class="text-xs text-muted-foreground">—</span>
            </TableCell>
            <TableCell class="font-mono text-[11px] text-muted-foreground">
              <span v-for="citationId in citationLabels(feature.citations)" :key="citationId" class="mr-1">{{ citationId }}</span>
              <span v-if="!citationLabels(feature.citations).length">—</span>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <!-- 窄屏降级：每行一卡，字段变成「标签: 值」 -->
      <div class="space-y-2 md:hidden" data-testid="blueprint-impact-cards">
        <div
          v-for="(feature, index) in affectedFeatures"
          :key="`card-${feature.feature}-${index}`"
          class="card space-y-1.5 p-3"
          data-testid="blueprint-impact-card"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-medium">{{ feature.feature }}</span>
            <Badge v-if="kindMeta(feature.kind)" :variant="kindMeta(feature.kind)!.variant" :data-kind="feature.kind">
              {{ t(`knowledge.blueprints.impact.${kindMeta(feature.kind)!.labelKey}`) }}
            </Badge>
            <Badge v-else variant="outline" :data-kind="feature.kind">
              {{ feature.kind }}
            </Badge>
          </div>
          <p class="text-xs text-muted-foreground">
            {{ t('knowledge.blueprints.tabPanel.filterRepository') }}: {{ repoLabels(feature.repository_ids) }}
          </p>
          <BlueprintBlockList
            v-if="feature.description?.length"
            :blocks="feature.description"
            :section-path="`impact_analysis.affected_features[${feature.feature}].description`"
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
    </div>

    <!-- ③ 回归范围：行式呈现（缺列头文案键，⛔ 不发明） -->
    <div v-if="regressionScope.length" data-field="regression-scope" class="space-y-1.5">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.impact.level') }}
      </p>
      <div
        v-for="(scope, index) in regressionScope"
        :key="`${scope.area ?? index}`"
        class="flex flex-wrap items-center gap-2 text-xs"
        data-testid="blueprint-regression-row"
      >
        <Badge v-if="levelMeta(scope.level)" :variant="levelMeta(scope.level)!.variant" :data-level="scope.level">
          {{ t(`knowledge.blueprints.impact.${levelMeta(scope.level)!.labelKey}`) }}
        </Badge>
        <Badge v-else variant="outline" :data-level="scope.level ?? ''">
          {{ scope.level ?? '—' }}
        </Badge>
        <span class="font-medium">{{ scope.area || '—' }}</span>
        <span class="text-muted-foreground">{{ scope.reason || '—' }}</span>
      </div>
    </div>

    <!-- ④ 兼容风险 / 回滚方案 -->
    <div v-if="compatRiskBlocks.length" data-field="compat-risks" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.impact.compatRisks') }}
      </p>
      <BlueprintBlockList
        :blocks="compatRiskBlocks"
        section-path="impact_analysis.compat_risks"
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

    <div v-if="rollbackBlocks.length" data-field="rollback-plan" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.impact.rollback') }}
      </p>
      <BlueprintBlockList
        :blocks="rollbackBlocks"
        section-path="impact_analysis.rollback_plan"
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

    <!-- ⑤ 数据迁移：⭐ reversible === false 才加不可逆徽标 -->
    <div v-if="dataMigrations.length" data-field="data-migrations" class="space-y-1.5">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.impact.dataMigration') }}
      </p>
      <div
        v-for="migration in dataMigrations"
        :key="migration.key"
        class="flex flex-wrap items-center gap-2 text-xs"
        data-testid="blueprint-data-migration"
      >
        <span>{{ migration.description }}</span>
        <Badge
          v-if="migration.irreversible"
          variant="destructive"
          data-irreversible="true"
          data-testid="blueprint-migration-irreversible"
        >
          reversible=false
        </Badge>
      </div>
    </div>
  </div>
</template>
