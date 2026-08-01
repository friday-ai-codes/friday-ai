<script setup lang="ts">
/**
 * 现状分析段（Phase 115-05，UI-SPEC §6.1 段 2 / §6.4）。
 *
 * **职责**：按 `repository_id` 分组呈现调研结论；`summary` 与每条 finding 的 `text`
 * 一律交给 `BlueprintBlockList`，⛔ 段组件内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⭐ **finding 的 `citations` 为空时亮 `destructive` 徽标**：schema 把 `citations` 列为 finding
 * 的 required 键（`blueprint_schema.py` `current_state_analysis.items.findings.required`），
 * 缺失是**质量信号**而不是「这条没引用而已」——⛔ 不隐藏。无证据的结论被当成有据放行，是本段
 * 最贵的失败模式（T-115-46）。
 *
 * ⭐ **跨段跳转一律 emit 给页面**：`related_feature_points` 的 chip 点击 emit
 * `goto-anchor('fp-<功能点 id>')`，⛔ 段内不自行调用任何滚动 API —— 88px 偏移常量归页面统一
 * 处理，段内自己滚会与 `AnchorNavLayout` 的偏移分叉（T-115-47）。
 *
 * **分工边界（P-4）**：`<section id="current_state_analysis">` 容器与导航项由页面无条件渲染。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补，见 115-05-SUMMARY §i18n）**：「现状综述」小标题与
 * `kind` 四档中文名无键 ⇒ 综述不渲染小标题（身份走 `data-field="summary"`），`kind` 徽标渲染
 * schema 原样 token（颜色由 `variant` 承载）；「缺引用」无键 ⇒ 降级复用 `citation.empty`，
 * 身份由 `data-missing-citations="true"` 承载。
 */

import type { SelectionPayload } from '../BlueprintBlockList.vue'
import type { BlueprintCurrentStateAnalysis, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import BlueprintBlockList from '../BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  analysis?: BlueprintCurrentStateAnalysis[]
  repoNames?: Record<string, string>
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  analysis: () => [],
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

/** `kind` 四档 → 徽标 variant（未知值退 `outline`，⛔ 不发明第五档）。 */
const KIND_VARIANT: Record<string, 'info' | 'warning' | 'destructive' | 'secondary'> = {
  capability: 'info',
  gap: 'warning',
  risk: 'destructive',
  convention: 'secondary',
}

const groups = computed(() => props.analysis ?? [])

function repoLabel(repositoryId: string): string {
  return props.repoNames?.[repositoryId] || repositoryId
}

function kindVariant(kind: string): 'info' | 'warning' | 'destructive' | 'secondary' | 'outline' {
  return KIND_VARIANT[kind] ?? 'outline'
}

/** `kind` 四档 → 中文名；未知值回落 schema 原样 token（⛔ 不发明第五档文案）。 */
const KIND_LABEL_KEY: Record<string, string> = {
  capability: 'kindCapability',
  gap: 'kindGap',
  risk: 'kindRisk',
  convention: 'kindConvention',
}

function kindLabel(kind: string): string {
  const suffix = KIND_LABEL_KEY[kind]
  return suffix ? t(`knowledge.blueprints.state.${suffix}`) : String(kind ?? '')
}

/** ⭐ 质量信号判据：`citations` 缺失或为空数组都算缺引用。 */
function missingCitations(citationIds: string[] | undefined): boolean {
  return !Array.isArray(citationIds) || citationIds.length === 0
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div data-testid="blueprint-current-state" class="space-y-4">
    <CompactEmptyState
      v-if="!groups.length"
      icon="lucide--scan-eye"
      :title="t('knowledge.blueprints.sectionEmpty', { name: t('knowledge.blueprints.section.currentStateAnalysis') })"
    />

    <template v-else>
      <div
        v-for="group in groups"
        :key="group.repository_id"
        class="card"
        data-testid="blueprint-current-state-group"
        :data-repository-id="group.repository_id"
      >
        <div class="flex items-center gap-2 border-b border-border/50 px-5 py-3.5">
          <span class="icon-[lucide--folder-git-2] text-primary" aria-hidden="true" />
          <h3 class="text-base font-semibold">
            {{ repoLabel(group.repository_id) }}
          </h3>
          <Badge variant="muted">
            {{ (group.findings ?? []).length }}
          </Badge>
        </div>

        <div class="space-y-4 p-5">
          <div v-if="group.summary?.length" data-field="summary">
            <p class="mb-1.5 text-xs font-medium text-muted-foreground">
              {{ t('knowledge.blueprints.section.currentStateSummary') }}
            </p>
            <BlueprintBlockList
              :blocks="group.summary"
              :section-path="`current_state_analysis[${group.repository_id}].summary`"
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

          <div
            v-for="finding in group.findings ?? []"
            :key="finding.id"
            class="space-y-1.5"
            data-testid="blueprint-finding"
            :data-finding-id="finding.id"
          >
            <div class="flex flex-wrap items-center gap-2">
              <Badge :variant="kindVariant(finding.kind)" :data-kind="finding.kind">
                {{ kindLabel(finding.kind) }}
              </Badge>
              <h4 v-if="finding.topic" class="text-base font-semibold">
                {{ finding.topic }}
              </h4>
              <!-- ⭐ 缺引用是质量信号，⛔ 不隐藏 -->
              <Badge
                v-if="missingCitations(finding.citations)"
                variant="destructive"
                data-missing-citations="true"
                data-testid="blueprint-finding-missing-citations"
              >
                {{ t('knowledge.blueprints.state.missingCitations') }}
              </Badge>
            </div>

            <BlueprintBlockList
              v-if="finding.text?.length"
              :blocks="finding.text"
              :section-path="`current_state_analysis[${group.repository_id}].findings[${finding.id}].text`"
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

            <div v-if="finding.related_feature_points?.length" class="flex flex-wrap gap-1">
              <button
                v-for="fp in finding.related_feature_points"
                :key="fp"
                type="button"
                class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground hover:border-primary/40 hover:text-primary"
                data-testid="blueprint-feature-point-chip"
                @click="emit('goto-anchor', `fp-${fp}`)"
              >
                {{ fp }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
