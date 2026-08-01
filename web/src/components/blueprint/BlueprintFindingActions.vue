<script setup lang="ts">
/**
 * AI 审查发现（`kind === 'ai_review_finding'`）的两个处置动作（Phase 115-04，UI-SPEC §7.8）。
 *
 * ⭐ **本组件是 finding 线程唯一的动作面** —— 「已修复」走 `threads/<id>/resolve/`、
 * 「误报忽略」走 `threads/<id>/dismiss/`，两者入参都是 `{reason}` 且**必填非空**。
 * finding 线程**不给作答输入框**：114 对 finding 走 `answer` 通道**一律 400**，且回灌链
 * `REFLOW_KINDS` fail-closed 过滤。分流因此做在渲染层（`BlueprintThreadCard` 的
 * `v-if` / `v-else` 两条互斥分支），⛔ 不做「统一输入框 + 提交时按 kind 切端点」。
 *
 * ⭐ **不受可编辑闸约束**（§7.9 末条）：后端未对 `resolve/` `dismiss/` 加状态闸，
 * 且处置 BLOCKER 是**超界死锁的唯一正向出口** —— `readonly === true` 时本组件仍然渲染。
 * 这与 `BlueprintThreadComposer`「不存在于 DOM」的处理刻意不同。
 *
 * ⭐ **弹窗用受控 `Dialog` 而不是 `useConfirmDialog`**：后者没有输入框，而这里的理由是必填项。
 * 形状照 `~/components/accessTokens/AccessTokenRevealDialog.vue`（受控 `open` + `update:open`）。
 *
 * ⛔ **前端不拼装结论文本**：后端自行把处置理由写成带动作前缀与操作者署名的结论消息，
 * 提交成功后重取线程即可看到那一条；前端只负责把理由原样送上去。
 *
 * 安全：理由全程走 Vue mustache 文本插值，不使用任何原始 HTML 注入指令。
 */

import { computed, nextTick, ref } from 'vue'
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
import { Textarea } from '~/components/ui/textarea'

const props = withDefaults(defineProps<{
  threadId: string
  submitting?: boolean
}>(), {
  submitting: false,
})

const emit = defineEmits<{
  resolve: [threadId: string, reason: string]
  dismiss: [threadId: string, reason: string]
}>()

const { t } = useI18n()

type FindingAction = 'resolve' | 'dismiss'

const open = ref(false)
const action = ref<FindingAction>('resolve')
const reason = ref('')
const reasonInput = ref<InstanceType<typeof Textarea> | null>(null)

/** 空 / 纯空格一律不可提交（后端同样 400，双保险）。 */
const isReasonEmpty = computed(() => reason.value.trim().length === 0)
const canSubmit = computed(() => !isReasonEmpty.value && !props.submitting)

const dialogTitle = computed(() =>
  action.value === 'resolve'
    ? t('knowledge.blueprints.finding.resolveTitle')
    : t('knowledge.blueprints.finding.dismissTitle'),
)

function openDialog(next: FindingAction): void {
  action.value = next
  reason.value = ''
  open.value = true
}

function setOpen(value: boolean): void {
  open.value = value
}

/** reka-ui 的 `open-auto-focus`：初始焦点落在理由输入框而不是关闭按钮。 */
function focusReason(event: Event): void {
  event.preventDefault()
  void nextTick(() => {
    const el = (reasonInput.value as unknown as { $el?: HTMLElement } | null)?.$el
    if (el && typeof el.focus === 'function')
      el.focus()
  })
}

function submit(): void {
  if (!canSubmit.value)
    return
  const value = reason.value.trim()
  if (action.value === 'resolve')
    emit('resolve', props.threadId, value)
  else
    emit('dismiss', props.threadId, value)
  open.value = false
}
</script>

<template>
  <div data-testid="blueprint-finding-actions" class="flex flex-wrap items-center gap-2">
    <Button
      size="sm"
      variant="outline"
      data-testid="blueprint-finding-resolve"
      :disabled="submitting"
      @click="openDialog('resolve')"
    >
      <span class="icon-[lucide--check-check] mr-1.5" aria-hidden="true" />
      {{ t('knowledge.blueprints.finding.resolve') }}
    </Button>
    <Button
      size="sm"
      variant="ghost"
      data-testid="blueprint-finding-dismiss"
      :disabled="submitting"
      @click="openDialog('dismiss')"
    >
      <span class="icon-[lucide--x-circle] mr-1.5" aria-hidden="true" />
      {{ t('knowledge.blueprints.finding.dismiss') }}
    </Button>

    <Dialog :open="open" @update:open="setOpen">
      <DialogContent
        data-testid="blueprint-finding-reason-dialog"
        class="max-w-md"
        @open-auto-focus="focusReason"
      >
        <DialogHeader>
          <DialogTitle>{{ dialogTitle }}</DialogTitle>
          <DialogDescription>
            {{ t('knowledge.blueprints.finding.reasonLabel') }}
          </DialogDescription>
        </DialogHeader>

        <Textarea
          ref="reasonInput"
          v-model="reason"
          data-testid="blueprint-finding-reason-input"
          class="min-h-24 text-sm"
          :placeholder="t('knowledge.blueprints.finding.reasonPlaceholder')"
        />
        <p v-if="isReasonEmpty" class="text-xs text-destructive">
          {{ t('knowledge.blueprints.finding.reasonRequired') }}
        </p>

        <DialogFooter>
          <Button
            size="sm"
            data-testid="blueprint-finding-reason-submit"
            :disabled="!canSubmit"
            @click="submit"
          >
            {{ t('knowledge.blueprints.finding.confirm') }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
