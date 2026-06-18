<script setup lang="ts">
/**
 * ：协商卡片。
 *
 * 渲染 ask_clarification 工具暴露的「问题 + ABCD 选项 + 自由输入」UI；
 * 提交后调 `POST /api/chat/clarifications/{id}/answer/`，成功 → 切到「已回复」
 * 态保留在消息流；失败 → 错误提示，仍允许重试。
 *
 * 后端 endpoint 已在 `chat/views.py:ClarificationAnswerView` 落 trace + Message
 * + 后台触发 `Command(resume=...)` —— 前端**不再 emit 新 user message**，
 * 答复内容由后端单独写 Message(kind=clarification_answer) 完成（防双发）。
 */
import type { ClarificationPayload } from '~/types/clarification'
import { postClarificationAnswer } from '~/api/chat'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{
  payload: ClarificationPayload
}>()

const chatStore = useChatStore()

const selectedId = ref<string>('')
const freeformText = ref<string>('')
const submitting = ref(false)
const skipping = ref(false)
const errorMessage = ref<string>('')

const isAnswered = computed(() => props.payload.status === 'answered')

const canSubmit = computed(() => {
  if (isAnswered.value || submitting.value)
    return false
  return Boolean(selectedId.value || freeformText.value.trim())
})

const resolvedAnswerLabel = computed(() => {
  const ans = props.payload.answer
  if (!ans)
    return ''
  if (ans.freeform_text)
    return ans.freeform_text
  if (ans.selected_option_id) {
    const opt = props.payload.options.find(o => o.id === ans.selected_option_id)
    return opt?.label || ans.selected_option_id
  }
  return ''
})

function formatAnsweredAt(iso?: string): string {
  if (!iso)
    return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  }
  catch {
    return iso
  }
}

async function submit() {
  if (!canSubmit.value)
    return
  submitting.value = true
  errorMessage.value = ''
  try {
    const resp = await postClarificationAnswer(props.payload.clarification_id, {
      selected_option_id: selectedId.value || undefined,
      freeform_text: freeformText.value.trim() || undefined,
    })
    chatStore.markClarificationAnswered(props.payload.clarification_id, {
      selected_option_id: resp.selected_option_id,
      freeform_text: resp.freeform_text,
      answered_at: resp.answered_at,
    })
  }
  catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } }, message?: string }
    errorMessage.value = e?.response?.data?.detail || e?.message || '提交失败，请重试'
  }
  finally {
    submitting.value = false
  }
}

/**
 * 跳过本次澄清：不提交答复，让后端基于现有信息直接作答。
 * 走 conversation 维度的 skip endpoint（store action 已封装乐观更新 + 轮询）。
 */
async function skip() {
  if (submitting.value || skipping.value)
    return
  skipping.value = true
  errorMessage.value = ''
  try {
    await chatStore.skipClarification()
  }
  catch (err: unknown) {
    const e = err as { message?: string }
    errorMessage.value = e?.message || '跳过失败，请重试'
  }
  finally {
    skipping.value = false
  }
}
</script>

<template>
  <div class="card mt-2 animate-fade-in">
    <!-- 头部 -->
    <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
      <span class="icon-[lucide--help-circle] text-primary" />
      <span class="text-sm font-semibold">还需要确认一下</span>
      <Badge :variant="isAnswered ? 'default' : 'info'" class="ml-auto">
        {{ isAnswered ? '已回复' : '待回复' }}
      </Badge>
    </div>

    <!-- 内容区 -->
    <div class="p-4 space-y-3">
      <p class="text-sm text-foreground whitespace-pre-wrap">
        {{ payload.question }}
      </p>

      <!-- 选项列表（用 button 实现单选；shadcn-vue 项目无 RadioGroup） -->
      <div role="radiogroup" :aria-disabled="isAnswered" class="space-y-2">
        <button
          v-for="opt in payload.options"
          :key="opt.id"
          type="button"
          role="radio"
          :aria-checked="selectedId === opt.id"
          :disabled="isAnswered || submitting"
          class="w-full text-left rounded-lg border px-3 py-2 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          :class="[
            selectedId === opt.id
              ? 'border-primary bg-primary/5'
              : 'border-border hover:border-primary/50 hover:bg-muted/30',
          ]"
          @click="selectedId = opt.id"
        >
          <div class="flex items-start gap-2">
            <span
              class="mt-0.5 size-4 shrink-0 rounded-full border-2 transition-colors"
              :class="[
                selectedId === opt.id
                  ? 'border-primary bg-primary'
                  : 'border-border',
              ]"
            />
            <div class="min-w-0 flex-1">
              <div class="text-sm font-medium">
                {{ opt.label }}
              </div>
              <div v-if="opt.hint" class="text-xs text-muted-foreground mt-0.5">
                {{ opt.hint }}
              </div>
            </div>
          </div>
        </button>
      </div>

      <!-- 自由输入兜底（allow_freeform=false 时不渲染） -->
      <div v-if="payload.allow_freeform && !isAnswered">
        <label class="text-xs text-muted-foreground font-medium">
          或自由输入（可选）
        </label>
        <Textarea
          v-model="freeformText"
          :disabled="submitting"
          rows="2"
          placeholder="如果以上选项都不准确，可以在这里描述..."
          class="mt-1 text-sm"
        />
      </div>

      <!-- 已回复态摘要 -->
      <div v-if="isAnswered && payload.answer" class="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2">
        <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span class="icon-[lucide--check-circle-2] text-emerald-500" />
          <span>已回复 · {{ formatAnsweredAt(payload.answer.answered_at) }}</span>
        </div>
        <div v-if="resolvedAnswerLabel" class="mt-1 text-sm">
          选择：{{ resolvedAnswerLabel }}
        </div>
      </div>

      <p v-if="errorMessage" class="text-destructive text-xs">
        {{ errorMessage }}
      </p>
    </div>

    <!-- 底部操作区 -->
    <div v-if="!isAnswered" class="px-4 pb-4 pt-2 flex items-center gap-2">
      <Button
        variant="ghost"
        class="shrink-0 text-muted-foreground"
        :disabled="submitting || skipping"
        @click="skip"
      >
        <span v-if="skipping" class="icon-[lucide--loader-2] animate-spin mr-2" />
        跳过
      </Button>
      <Button
        class="flex-1"
        :disabled="!canSubmit"
        @click="submit"
      >
        <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin mr-2" />
        提交答复
      </Button>
    </div>
  </div>
</template>
