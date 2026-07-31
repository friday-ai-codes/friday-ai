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

export interface BlueprintRejectPayload {
  comment: string
  anchor?: {
    block_id: string
    start_offset: number
    end_offset: number
    quoted_text: string
  }
}

const props = withDefaults(defineProps<{
  open: boolean
  /** 当前修订轮次；提示里显示的是 `revisionRound + 1`。 */
  revisionRound?: number
  /** 用户此前的选区；存在时弹窗顶部显示引文预览与「一并带上」开关。 */
  presetAnchor?: BlueprintRejectAnchor | null
  submitting?: boolean
}>(), {
  revisionRound: 0,
  presetAnchor: null,
  submitting: false,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'submit': [payload: BlueprintRejectPayload]
}>()

const { t } = useI18n()

const comment = ref('')
const keepAnchor = ref(true)
const commentInput = ref<InstanceType<typeof Textarea> | null>(null)

/** 空 / 纯空格一律不可提交。 */
const isCommentEmpty = computed(() => comment.value.trim().length === 0)
const canSubmit = computed(() => !isCommentEmpty.value && !props.submitting)

watch(() => props.open, (value) => {
  if (value) {
    comment.value = ''
    keepAnchor.value = true
  }
})

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
  const payload: BlueprintRejectPayload = { comment: comment.value.trim() }
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
