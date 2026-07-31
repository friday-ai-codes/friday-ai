<script setup lang="ts">
/**
 * 仓库关联卡（Phase 115-05，UI-SPEC §6.3 逐行实现）。
 *
 * **职责**：把 `repo_associations[]` 的一条排版成一张卡；所有 Block[]
 * （`responsibility` / `rationale.text` / `fitness.reasons` / `planned_change_summary` /
 * `support_needed`）一律交给 `BlueprintBlockList`，⛔ 卡内不自行处理批注与引用
 * （UI-SPEC §13.3：批注层的唯一实现点是 `BlueprintBlock.vue`）。
 *
 * **SC-3 的落点**：卡右上角 `RouterLink to="/repositories/{repository_id}"` —— 评审人
 * 从方案里可以一步进到那个仓库。
 *
 * ⭐ **`unsuitable` 时的「替代建议」按 `fitness.reasons` 自由文本原样展示**（UI-SPEC §0.2
 * 判定 6，同时定夺 STATE 登记的「Phase 112 残留 PARTIAL / FLOW-02：替代建议无结构化字段」）：
 * ⛔ 不补 schema 字段、⛔ 不对 `reasons` 做正则切分/解析。前端只是呈现方，为了呈现去改一份
 * 已锁定的后端 schema 不划算；真要结构化，该在产出侧（114 链路）做，不在这里猜。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补，见 115-05-SUMMARY §i18n）**：
 * - 「选仓理由」无键 ⇒ 降级用 `repo.role`（关联角色）作组头，身份由 `data-field="rationale"` 承载；
 * - 「会被用到的能力」无键 ⇒ 降级复用 `knowledge.entity.associations.capabilities`（关联能力）；
 * - 「跨组协作」/「已在确认门锁定」/「未经确认门锁定」无键 ⇒ 跨组标记渲染 schema 原样 token，
 *   确认门两档复用 `thread.kindRepoConfirmation`（确认门）+ 图标 + `data-confirmed-at-gate` 区分。
 */

import type { SelectionPayload } from './BlueprintBlockList.vue'
import type { BlueprintRepoAssociation, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import BlueprintBlockList from './BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  association: BlueprintRepoAssociation
  /** 页面解析出的仓名（缺省时回落条目自带的 `repository_name`）。 */
  repoName?: string
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  repoName: '',
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

/** ⭐ `role` **双色**（UI-SPEC §6.3）：⛔ 不发明第三色，未知值退 `outline` 并原样显示 token。 */
const ROLE_META: Record<string, { variant: 'default' | 'secondary', labelKey: string }> = {
  direct: { variant: 'default', labelKey: 'roleDirect' },
  indirect: { variant: 'secondary', labelKey: 'roleIndirect' },
}

/** `fitness.verdict` 三档。 */
const VERDICT_META: Record<string, { variant: 'success' | 'warning' | 'destructive', labelKey: string }> = {
  suitable: { variant: 'success', labelKey: 'fitnessSuitable' },
  partial: { variant: 'warning', labelKey: 'fitnessPartial' },
  unsuitable: { variant: 'destructive', labelKey: 'fitnessUnsuitable' },
}

const repoLabel = computed(() => props.repoName || props.association.repository_name || props.association.repository_id)

const roleMeta = computed(() => ROLE_META[props.association.role] ?? null)

const verdict = computed(() => props.association.fitness?.verdict ?? '')
const verdictMeta = computed(() => VERDICT_META[verdict.value] ?? null)

const isDirect = computed(() => props.association.role === 'direct')
const isIndirect = computed(() => props.association.role === 'indirect')

/** 五处 Block[] 统一在此收窄，模板里只判长度（避免可选链在模板中的窄化歧义）。 */
const responsibilityBlocks = computed(() => props.association.responsibility ?? [])
const rationaleBlocks = computed(() => props.association.rationale?.text ?? [])
const fitnessReasonBlocks = computed(() => props.association.fitness?.reasons ?? [])
const plannedChangeBlocks = computed(() => props.association.planned_change_summary ?? [])
const supportNeededBlocks = computed(() => props.association.support_needed ?? [])

const constraintRefs = computed(() => {
  const refs = props.association.rationale?.constraint_refs
  return Array.isArray(refs) ? refs.filter(ref => typeof ref === 'string' && ref) : []
})

/** indirect 专属：会被用到的能力（条目形状零 schema 约束 ⇒ 逐键可选链，缺键渲染「—」）。 */
const capabilities = computed(() => {
  const list = props.association.capabilities_used
  if (!Array.isArray(list))
    return []
  return list.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>
    return {
      key: `${index}`,
      name: typeof item.name === 'string' && item.name ? item.name : '—',
      location: typeof item.location === 'string' && item.location ? item.location : '—',
      howUsed: typeof item.how_used === 'string' && item.how_used ? item.how_used : '—',
    }
  })
})

/** `routing_evidence` 只声明 `type: object` ⇒ 逐键收窄，⛔ 不做类型断言。 */
const routingScore = computed(() => {
  const value = props.association.routing_evidence?.score
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : ''
})

const routingConfidence = computed(() => {
  const value = props.association.routing_evidence?.confidence
  return typeof value === 'string' && value ? value : ''
})

/** ⭐ 严格判等：只有显式 `true` 才是跨组协作（缺键 ≠ 跨组）。 */
const isCrossTeam = computed(() => props.association.routing_evidence?.cross_team === true)

const hasRouting = computed(() => Boolean(routingScore.value || routingConfidence.value || isCrossTeam.value))

const decidedByKey = computed(() => {
  if (props.association.decided_by === 'human')
    return 'decidedByHuman'
  if (props.association.decided_by === 'ai')
    return 'decidedByAi'
  return ''
})

/** `confirmed_at_gate` 三态：`true` 已锁定 / `false` 未锁定 / 缺键不渲染任何徽标。 */
const gateState = computed(() => {
  if (props.association.confirmed_at_gate === true)
    return 'true'
  if (props.association.confirmed_at_gate === false)
    return 'false'
  return ''
})

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div
    class="card p-4 space-y-3"
    data-testid="blueprint-repo-card"
    :data-role="association.role"
    :data-repository-id="association.repository_id"
  >
    <!-- 卡头：role 双色 + 仓名 + fitness 三档 + ⭐ 跳仓库页（SC-3） -->
    <div class="flex items-start gap-2">
      <Badge v-if="roleMeta" :variant="roleMeta.variant">
        {{ t(`knowledge.blueprints.repo.${roleMeta.labelKey}`) }}
      </Badge>
      <Badge v-else variant="outline">
        {{ association.role }}
      </Badge>

      <span class="text-sm font-semibold flex-1 min-w-0 truncate">{{ repoLabel }}</span>

      <Badge v-if="verdictMeta" :variant="verdictMeta.variant" :data-verdict="verdict">
        {{ t(`knowledge.blueprints.repo.${verdictMeta.labelKey}`) }}
      </Badge>

      <RouterLink
        :to="`/repositories/${association.repository_id}`"
        class="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-primary"
        data-testid="blueprint-repo-open"
      >
        <span class="icon-[lucide--external-link]" aria-hidden="true" />
        <span>{{ t('knowledge.blueprints.repo.openRepository') }}</span>
      </RouterLink>
    </div>

    <!-- 职责 -->
    <div v-if="responsibilityBlocks.length" data-field="responsibility" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.repo.responsibility') }}
      </p>
      <BlueprintBlockList
        :blocks="responsibilityBlocks"
        :section-path="`repo_associations[${association.repository_id}].responsibility`"
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

    <!-- 选仓理由（默认折叠） -->
    <Collapsible v-if="rationaleBlocks.length || constraintRefs.length" data-field="rationale">
      <CollapsibleTrigger class="flex w-full items-center gap-1.5 rounded-lg py-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground">
        <span class="icon-[lucide--chevron-right]" aria-hidden="true" />
        <span>{{ t('knowledge.blueprints.repo.rationale') }}</span>
      </CollapsibleTrigger>
      <CollapsibleContent class="space-y-2 pt-1.5">
        <BlueprintBlockList
          v-if="rationaleBlocks.length"
          :blocks="rationaleBlocks"
          :section-path="`repo_associations[${association.repository_id}].rationale.text`"
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
        <div v-if="constraintRefs.length" class="flex flex-wrap gap-1">
          <span
            v-for="ref in constraintRefs"
            :key="ref"
            class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
            data-testid="blueprint-repo-constraint-ref"
          >{{ ref }}</span>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <!-- 适配判定（默认折叠）：⭐ unsuitable 的「替代建议」在 reasons 里原样呈现 -->
    <Collapsible v-if="verdictMeta || fitnessReasonBlocks.length" data-field="fitness">
      <CollapsibleTrigger class="flex w-full items-center gap-1.5 rounded-lg py-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground">
        <span class="icon-[lucide--chevron-right]" aria-hidden="true" />
        <span>{{ t('knowledge.blueprints.repo.fitness') }}</span>
      </CollapsibleTrigger>
      <CollapsibleContent class="space-y-2 pt-1.5">
        <BlueprintBlockList
          v-if="fitnessReasonBlocks.length"
          :blocks="fitnessReasonBlocks"
          :section-path="`repo_associations[${association.repository_id}].fitness.reasons`"
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
      </CollapsibleContent>
    </Collapsible>

    <!-- direct 专属：本仓改动摘要 -->
    <div v-if="isDirect && plannedChangeBlocks.length" data-field="planned-change" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.repo.plannedChange') }}
      </p>
      <BlueprintBlockList
        :blocks="plannedChangeBlocks"
        :section-path="`repo_associations[${association.repository_id}].planned_change_summary`"
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

    <!-- indirect 专属：会被用到的能力 -->
    <div v-if="isIndirect && capabilities.length" data-field="capabilities-used" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.repo.capabilitiesUsed') }}
      </p>
      <ul class="space-y-1">
        <li
          v-for="capability in capabilities"
          :key="capability.key"
          class="text-xs text-muted-foreground"
          data-testid="blueprint-repo-capability"
        >
          <span class="font-medium text-foreground">{{ capability.name }}</span>
          <span class="font-mono"> · {{ capability.location }}</span>
          <span> · {{ capability.howUsed }}</span>
        </li>
      </ul>
    </div>

    <!-- 需要配合（有值才渲染） -->
    <div v-if="supportNeededBlocks.length" data-field="support-needed" class="space-y-1">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.repo.supportNeeded') }}
      </p>
      <BlueprintBlockList
        :blocks="supportNeededBlocks"
        :section-path="`repo_associations[${association.repository_id}].support_needed`"
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

    <!-- routing_evidence 一行 mono 小字 -->
    <div v-if="hasRouting" class="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
      <span>{{ t('knowledge.blueprints.repo.routing') }}</span>
      <span v-if="routingScore" data-testid="blueprint-repo-routing-score">{{ routingScore }}</span>
      <span v-if="routingConfidence">{{ routingConfidence }}</span>
      <Badge v-if="isCrossTeam" variant="warning" data-cross-team="true">
        {{ t('knowledge.blueprints.repo.crossTeam') }}
      </Badge>
    </div>

    <!-- 底部：决定人 + 确认门锁定状态 -->
    <div v-if="decidedByKey || gateState" class="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
      <span v-if="decidedByKey">{{ t(`knowledge.blueprints.repo.${decidedByKey}`) }}</span>
      <Badge v-if="gateState === 'true'" variant="success" data-confirmed-at-gate="true">
        <span class="icon-[lucide--check]" aria-hidden="true" />
        {{ t('knowledge.blueprints.repo.confirmedAtGate') }}
      </Badge>
      <Badge v-else-if="gateState === 'false'" variant="outline" data-confirmed-at-gate="false">
        <span class="icon-[lucide--minus-circle]" aria-hidden="true" />
        {{ t('knowledge.blueprints.repo.notConfirmedAtGate') }}
      </Badge>
    </div>
  </div>
</template>
