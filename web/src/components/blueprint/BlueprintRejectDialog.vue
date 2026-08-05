<script setup lang="ts">
/**
 * 人审驳回弹窗（Phase 115-04，FLOW-08，UI-SPEC §11.1 / §16）。
 *
 * ⭐ **驳回走受控 `Dialog`，⛔ 不走全局那个二次确认 composable** —— 它只有标题/正文/两个
 * 按钮、没有输入框，而 `comment` 是必填项（通过走它、驳回不走它，这是刻意的不对称）。
 * 形状照 `~/components/accessTokens/AccessTokenRevealDialog.vue`（受控 `open`
 * + `update:open`），`DialogTitle` 必填（缺了 reka-ui 会报 a11y 警告）。
 *
 * ⭐ **`comment` 必填非空**：空 / 纯空格 ⇒ 提交按钮 `disabled` + 输入框下方内联
 * `text-destructive` 提示。⛔ 不允许空评论驳回 —— 那会产生一条无理由的审计记录
 * （后端同样 400，双保险）。
 *
 * 底部常驻提示逐字取自 §16 的 `review.rejectBody`，插值 `n` 传 **`revisionRound + 1`**
 * （提示的是「驳回后将变成第几轮」，不是当前轮次）。
 *
 * 锚点开关的标签用 `review.rejectKeepAnchor`（「保留此划线」，115-06 补键后换回）。
 *
 * 安全：引文与理由全程 Vue mustache + `<pre>`，不使用任何原始 HTML 注入指令。
 */

import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'

/** 可选的划线锚点（形状与 `blueprint-review/reject/` 的 `anchor` 入参一致）。 */
export interface BlueprintRejectAnchor {
  blockId: string
  startOffset: number
  endOffset: number
  quotedText: string
}

/** 重跑范围（Phase 120，REDO-01）：与后端 `_REWORK_SCOPE_STAGES` 的键**逐字同集**。 */
export type BlueprintReworkScope = 'review' | 'merge' | 'repos' | 'full'

export interface BlueprintRejectPayload {
  comment: string
  anchor?: {
    block_id: string
    start_offset: number
    end_offset: number
    quoted_text: string
  }
  /** 缺省由后端回落 `merge`（改动前的唯一路径）⇒ 不传即旧行为。 */
  rework_scope?: BlueprintReworkScope
  /** 仅 `repos` 范围有意义；其它范围一律不传。 */
  rework_repository_ids?: string[]
}

const props = withDefaults(defineProps<{
  open: boolean
  /** 当前修订轮次；提示里显示的是 `revisionRound + 1`。 */
  revisionRound?: number
  /** 用户此前的选区；存在时弹窗顶部显示引文预览与「一并带上」开关。 */
  presetAnchor?: BlueprintRejectAnchor | null
  submitting?: boolean
  /**
   * 可选的仓库清单（`repos` 范围的勾选源，取自蓝图 `repo_associations`）。
   * 为空时**不渲染** `repos` 选项 —— 给不出可勾的仓还留着这个范围，只会让人选完发现
   * 什么都没重跑。
   */
  repositories?: Array<{ id: string, name: string }>
}>(), {
  revisionRound: 0,
  presetAnchor: null,
  submitting: false,
  repositories: () => [],
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'submit': [payload: BlueprintRejectPayload]
}>()

const { t } = useI18n()

const comment = ref('')
const keepAnchor = ref(true)
const commentInput = ref<InstanceType<typeof Textarea> | null>(null)

/**
 * 重跑范围（REDO-01）。默认 `merge` = 改动前的唯一路径 ⇒ 不改变既有肌肉记忆。
 *
 * ⚠️ 选 `repos` 但一个仓都没勾 ⇒ 不可提交：那等于「重跑指定仓，但没指定」，后端会
 * 零失效空转到 merge，用户以为点了却什么都没重跑（比报错更糟）。
 */
const scope = ref<BlueprintReworkScope>('merge')
const selectedRepositoryIds = ref<string[]>([])

const scopeOptions = computed(() => {
  const rows: BlueprintReworkScope[] = ['review', 'merge', 'full']
  // 有仓可勾才给 `repos`（见 props.repositories 注释）
  return props.repositories.length > 0 ? ['review', 'merge', 'repos', 'full'] as BlueprintReworkScope[] : rows
})

/** 空 / 纯空格一律不可提交。 */
const isCommentEmpty = computed(() => comment.value.trim().length === 0)
const needsRepoSelection = computed(
  () => scope.value === 'repos' && selectedRepositoryIds.value.length === 0,
)
const canSubmit = computed(
  () => !isCommentEmpty.value && !needsRepoSelection.value && !props.submitting,
)

watch(() => props.open, (value) => {
  if (value) {
    comment.value = ''
    keepAnchor.value = true
    scope.value = 'merge'
    selectedRepositoryIds.value = []
  }
})

function toggleRepository(id: string): void {
  const next = new Set(selectedRepositoryIds.value)
  if (next.has(id))
    next.delete(id)
  else next.add(id)
  selectedRepositoryIds.value = [...next]
}

function setOpen(value: boolean): void {
  emit('update:open', value)
}

/** reka-ui 的 `open-auto-focus`：初始焦点落在理由输入框（§18.2）。 */
function focusComment(event: Event): void {
  event.preventDefault()
  void nextTick(() => {
    const el = (commentInput.value as unknown as { $el?: HTMLElement } | null)?.$el
    if (el && typeof el.focus === 'function')
      el.focus()
  })
}

function submit(): void {
  if (!canSubmit.value)
    return
  const anchor = props.presetAnchor
  const payload: BlueprintRejectPayload = {
    comment: comment.value.trim(),
    rework_scope: scope.value,
  }
  if (scope.value === 'repos')
    payload.rework_repository_ids = [...selectedRepositoryIds.value]
  if (anchor && keepAnchor.value) {
    payload.anchor = {
      block_id: anchor.blockId,
      start_offset: anchor.startOffset,
      end_offset: anchor.endOffset,
      quoted_text: anchor.quotedText,
    }
  }
  emit('submit', payload)
}
</script>

<template>
  <Dialog :open="open" @update:open="setOpen">
    <DialogContent
      data-testid="blueprint-reject-dialog"
      class="max-w-lg"
      @open-auto-focus="focusComment"
    >
      <DialogHeader>
        <DialogTitle>{{ t('knowledge.blueprints.review.rejectTitle') }}</DialogTitle>
        <DialogDescription>
          {{ t('knowledge.blueprints.review.rejectBody', { n: revisionRound + 1 }) }}
        </DialogDescription>
      </DialogHeader>

      <div v-if="presetAnchor" data-testid="blueprint-reject-anchor" class="space-y-2">
        <pre class="whitespace-pre-wrap break-words rounded-lg bg-muted/50 px-2.5 py-1.5 font-mono text-xs leading-5">{{ presetAnchor.quotedText }}</pre>
        <div class="flex items-center gap-2">
          <Switch
            v-model="keepAnchor"
            data-testid="blueprint-reject-keep-anchor"
          />
          <span class="text-xs text-foreground">{{ t('knowledge.blueprints.review.rejectKeepAnchor') }}</span>
        </div>
      </div>

      <Textarea
        ref="commentInput"
        v-model="comment"
        data-testid="blueprint-reject-comment"
        class="min-h-24 text-sm"
        :placeholder="t('knowledge.blueprints.review.rejectReasonPlaceholder')"
      />
      <p v-if="isCommentEmpty" class="text-xs text-destructive">
        {{ t('knowledge.blueprints.review.rejectReasonRequired') }}
      </p>

      <!-- ⭐ 重跑范围（REDO-01）：打回不只有一种返工。默认 merge = 改动前的唯一路径。 -->
      <fieldset class="space-y-1.5" data-testid="blueprint-reject-scope">
        <legend class="text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.review.reworkScopeLabel') }}
        </legend>
        <label
          v-for="option in scopeOptions"
          :key="option"
          class="flex cursor-pointer items-start gap-2 rounded-lg px-1 py-0.5 text-sm hover:bg-muted/40"
        >
          <input
            v-model="scope"
            type="radio"
            :value="option"
            :data-scope="option"
            class="mt-1"
          >
          <span class="min-w-0">
            <span class="block">{{ t(`knowledge.blueprints.review.reworkScope.${option}`) }}</span>
            <span class="block text-xs text-muted-foreground">
              {{ t(`knowledge.blueprints.review.reworkScopeHint.${option}`) }}
            </span>
          </span>
        </label>

        <!-- repos 范围：勾选要重跑的仓（一个都不勾则不可提交，理由见 needsRepoSelection） -->
        <div v-if="scope === 'repos'" class="ml-6 space-y-1" data-testid="blueprint-reject-repos">
          <label
            v-for="repo in repositories"
            :key="repo.id"
            class="flex cursor-pointer items-center gap-2 text-sm"
          >
            <input
              type="checkbox"
              :value="repo.id"
              :checked="selectedRepositoryIds.includes(repo.id)"
              @change="toggleRepository(repo.id)"
            >
            <span class="min-w-0 truncate">{{ repo.name || repo.id.slice(0, 8) }}</span>
          </label>
          <p v-if="needsRepoSelection" class="text-xs text-destructive">
            {{ t('knowledge.blueprints.review.reworkScopeRepoRequired') }}
          </p>
        </div>
      </fieldset>

      <DialogFooter>
        <Button
          variant="destructive"
          size="sm"
          data-testid="blueprint-reject-submit"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ t('knowledge.blueprints.review.rejectConfirm') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
