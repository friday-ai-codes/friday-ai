<script setup lang="ts">
/**
 * 确认门单仓行（Phase 115-07，UI-SPEC §11.3 / §16 / §13.5）。
 *
 * ## ① 本行只 emit，不发请求
 *
 * 四个行内动作（改判 role / 修改职责 / 移除 / 升级深调研）一律 emit 给
 * `BlueprintGatePanel`，由面板统一走「一次 POST + 双 invalidate」范式。⛔ 本行零 `useMutation`、
 * 零乐观更新 —— 行内状态（选中的 role、职责草稿）**不预写**，一切以重取到的快照为准。
 *
 * ## ② ⭐ 二次确认与受控 Dialog 的分工（⛔ 不要统一）
 *
 * - **移除** 是破坏性动作 ⇒ `useConfirmDialog()`，四字段逐字取自 §16 的 i18n 键；
 * - **修改职责** 需要用户输入 ⇒ ⛔ **不能用 `useConfirmDialog`（它没有输入框）**，改用受控
 *   小 `Dialog` + `Textarea`；空 / 纯空格时提交按钮 `disabled`。
 *
 * ## ③ ⭐ pending 调研态是硬闸
 *
 * `props.pending`（该仓命中快照的 `pending_research_repository_ids`）为真时**行内全部动作
 * `disabled`** 并显示 `icon-[lucide--loader-2] animate-spin` + 「调研中」。漏判会让用户在调研
 * 途中提交动作，后端拒绝且体验断裂（T-115-63）。
 *
 * ## ④ ⭐ `rerun` 挂在「修改职责」而非「升级深调研」（对 PLAN 措辞的一处订正）
 *
 * 实读 `blueprint_gate_views.py:338` 与 115-02 的 `~/api/blueprints`：`rerun` 是
 * **`edit-responsibility/` 的入参**（职责文本变化是否改变调研范围无法机械判定 ⇒ 默认不重调研，
 * 显式勾选才触发）；`upgrade-research/` **只收 `repository_id`**，升级本身即是重开深调研，
 * 且该按钮⭐ **只对 `indirect` 行渲染**（`direct` 已经是深调研结论的超集，没有可升级的余地）。
 * ⇒ 勾选框渲染在职责编辑弹窗里，升级按钮不带勾选。⛔ 不给 `upgrade-research/` 编造入参。
 */

import type { BlueprintGateRepo } from '~/types/blueprint'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Textarea } from '~/components/ui/textarea'
import { useConfirmDialog } from '~/composables/useConfirmDialog'

const props = withDefaults(defineProps<{
  repo: BlueprintGateRepo
  pending?: boolean
  submitting?: boolean
}>(), {
  pending: false,
  submitting: false,
})

const emit = defineEmits<{
  'remove': [repositoryId: string]
  'reclassify': [repositoryId: string, role: 'direct' | 'indirect']
  'edit-responsibility': [repositoryId: string, text: string, rerun: boolean]
  'upgrade-research': [repositoryId: string]
}>()

const { t } = useI18n()
const { confirm } = useConfirmDialog()

/** role 双色（与 `RepoAssociationCard` 逐字一致，⛔ 组件内零颜色字面量）。 */
const ROLE_META: Record<string, { variant: 'default' | 'secondary', labelKey: string }> = {
  direct: { variant: 'default', labelKey: 'roleDirect' },
  indirect: { variant: 'secondary', labelKey: 'roleIndirect' },
}

/** `fitness.verdict` 三档（同上）。 */
const VERDICT_META: Record<string, { variant: 'success' | 'warning' | 'destructive', labelKey: string }> = {
  suitable: { variant: 'success', labelKey: 'fitnessSuitable' },
  partial: { variant: 'warning', labelKey: 'fitnessPartial' },
  unsuitable: { variant: 'destructive', labelKey: 'fitnessUnsuitable' },
}

const role = computed(() => String(props.repo.role_suggestion ?? ''))
const roleMeta = computed(() => ROLE_META[role.value] ?? null)

const verdict = computed(() => String(props.repo.fitness?.verdict ?? ''))
const verdictMeta = computed(() => VERDICT_META[verdict.value] ?? null)

const repoName = computed(() =>
  props.repo.repository_name || t('knowledge.blueprints.activity.repoUnknown'),
)

/** 证据 chip 数：`citations` 是数组就取长度，否则退化成键数（裸 JSONField ⇒ 逐键可选链）。 */
const evidenceCount = computed(() => {
  const evidence = props.repo.routing_evidence
  if (!evidence || typeof evidence !== 'object')
    return 0
  const citations = (evidence as { citations?: unknown }).citations
  if (Array.isArray(citations))
    return citations.length
  return Object.keys(evidence).length
})

/** ⭐ 唯一的可用性判据：调研中 / 面板正在提交 ⇒ 行内动作全禁。 */
const disabled = computed(() => props.pending || props.submitting)

/** 升级深调研只对 `indirect` 行渲染 —— `direct` 已经是深调研结论的超集。 */
const canUpgrade = computed(() => role.value === 'indirect')

// ── 修改职责：受控 Dialog + Textarea（⛔ 不走 useConfirmDialog）────────────────

const editOpen = ref(false)
const draft = ref('')
const rerun = ref(false)

watch(editOpen, (open) => {
  if (!open)
    return
  draft.value = props.repo.responsibility ?? ''
  rerun.value = false
})

const canSubmitEdit = computed(() => draft.value.trim().length > 0 && !props.submitting)

function onSubmitEdit(): void {
  if (!canSubmitEdit.value)
    return
  emit('edit-responsibility', props.repo.repository_id, draft.value.trim(), rerun.value)
  editOpen.value = false
}

// ── 其余三个动作 ──────────────────────────────────────────────────────────────

function onReclassify(next: 'direct' | 'indirect'): void {
  if (disabled.value || role.value === next)
    return
  emit('reclassify', props.repo.repository_id, next)
}

/** ⭐ 破坏性动作二次确认，四字段逐字取自 §16。 */
async function onRemove(): Promise<void> {
  const ok = await confirm({
    title: t('knowledge.blueprints.gate.removeTitle'),
    description: t('knowledge.blueprints.gate.removeBody'),
    confirmText: t('knowledge.blueprints.gate.removeConfirm'),
    variant: 'destructive',
  })
  if (ok)
    emit('remove', props.repo.repository_id)
}

function onUpgrade(): void {
  if (disabled.value)
    return
  emit('upgrade-research', props.repo.repository_id)
}
</script>

<template>
  <div
    class="space-y-2 rounded-xl border border-border p-3"
    data-testid="blueprint-gate-repo-row"
    :data-repository-id="repo.repository_id"
    :data-pending="pending ? 'true' : 'false'"
  >
    <!-- 行头：仓名 + role 双色 + fitness 三档 + 调研中指示 -->
    <div class="flex flex-wrap items-center gap-2">
      <span class="truncate text-sm font-medium">{{ repoName }}</span>

      <Badge v-if="roleMeta" :variant="roleMeta.variant" :data-role="role">
        {{ t(`knowledge.blueprints.repo.${roleMeta.labelKey}`) }}
      </Badge>

      <Badge v-if="verdictMeta" :variant="verdictMeta.variant" :data-verdict="verdict">
        {{ t(`knowledge.blueprints.repo.${verdictMeta.labelKey}`) }}
      </Badge>

      <Badge v-if="evidenceCount > 0" variant="outline" data-testid="blueprint-gate-evidence-count">
        {{ t('knowledge.blueprints.gate.evidenceCount', { n: evidenceCount }) }}
      </Badge>

      <span
        v-if="pending"
        class="ml-auto flex items-center gap-1 text-xs text-muted-foreground"
        data-testid="blueprint-gate-row-pending"
        aria-live="polite"
      >
        <span class="icon-[lucide--loader-2] size-3.5 animate-spin" aria-hidden="true" />
        {{ t('knowledge.blueprints.gate.researching') }}
      </span>
    </div>

    <!-- 职责与现状摘要 -->
    <p v-if="repo.responsibility" class="text-xs text-muted-foreground">
      <span class="font-medium">{{ t('knowledge.blueprints.repo.responsibility') }}：</span>{{ repo.responsibility }}
    </p>
    <p v-if="repo.current_state_summary" class="line-clamp-2 text-xs text-muted-foreground">
      {{ repo.current_state_summary }}
    </p>

    <!-- 行内动作条 -->
    <div class="flex flex-wrap items-center gap-2">
      <!-- 改判 role：二选一 segmented control，即时提交 -->
      <div class="inline-flex overflow-hidden rounded-md border border-border" role="group" :aria-label="t('knowledge.blueprints.gate.reclassifyRole')">
        <Button
          type="button"
          size="sm"
          class="rounded-none"
          :variant="role === 'direct' ? 'default' : 'ghost'"
          :disabled="disabled"
          data-testid="blueprint-gate-role-direct"
          @click="onReclassify('direct')"
        >
          {{ t('knowledge.blueprints.repo.roleDirect') }}
        </Button>
        <Button
          type="button"
          size="sm"
          class="rounded-none"
          :variant="role === 'indirect' ? 'default' : 'ghost'"
          :disabled="disabled"
          data-testid="blueprint-gate-role-indirect"
          @click="onReclassify('indirect')"
        >
          {{ t('knowledge.blueprints.repo.roleIndirect') }}
        </Button>
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        :disabled="disabled"
        data-testid="blueprint-gate-edit-responsibility"
        @click="editOpen = true"
      >
        {{ t('knowledge.blueprints.gate.editResponsibility') }}
      </Button>

      <Button
        v-if="canUpgrade"
        type="button"
        variant="outline"
        size="sm"
        :disabled="disabled"
        data-testid="blueprint-gate-upgrade-research"
        @click="onUpgrade"
      >
        {{ t('knowledge.blueprints.gate.upgradeResearch') }}
      </Button>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        class="ml-auto"
        :disabled="disabled"
        data-testid="blueprint-gate-remove-repo"
        @click="onRemove"
      >
        {{ t('knowledge.blueprints.gate.removeRepo') }}
      </Button>
    </div>

    <!-- ⭐ 修改职责：受控 Dialog + Textarea（useConfirmDialog 没有输入框，用不了） -->
    <Dialog v-model:open="editOpen">
      <DialogContent data-testid="blueprint-gate-responsibility-dialog">
        <DialogHeader>
          <DialogTitle>{{ t('knowledge.blueprints.gate.responsibilityTitle') }}</DialogTitle>
          <DialogDescription>{{ t('knowledge.blueprints.gate.responsibilityHint') }}</DialogDescription>
        </DialogHeader>

        <Textarea
          v-model="draft"
          rows="4"
          :placeholder="t('knowledge.blueprints.gate.responsibilityPlaceholder')"
          data-testid="blueprint-gate-responsibility-input"
        />

        <label class="flex items-center gap-2 text-xs text-muted-foreground">
          <Checkbox v-model="rerun" data-testid="blueprint-gate-responsibility-rerun" />
          {{ t('knowledge.blueprints.gate.rerunResearch') }}
        </label>

        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" @click="editOpen = false">
            {{ t('knowledge.blueprints.gate.cancel') }}
          </Button>
          <Button
            type="button"
            size="sm"
            :disabled="!canSubmitEdit"
            data-testid="blueprint-gate-responsibility-submit"
            @click="onSubmitEdit"
          >
            {{ t('knowledge.blueprints.gate.save') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
