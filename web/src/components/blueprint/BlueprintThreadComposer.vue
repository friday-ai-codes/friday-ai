<script setup lang="ts">
/**
 * 线程作答输入框（Phase 115-04，UI-SPEC §7.8）。
 *
 * ⭐ **本组件只服务非 finding 线程** —— `ai_clarification` / `human_comment` /
 * `repo_confirmation` 三类，提交后由父层调 `threads/<id>/answer/`。
 * `ai_review_finding` 的动作由 `BlueprintFindingActions` 承担，两者在
 * `BlueprintThreadCard` 的模板里**物理互斥**（渲染层硬分流，114-REVIEW CR-01）。
 *
 * ⭐ **不渲染 ≠ disabled**：`readonly` 的判定在父层做成 `v-if`（§7.9），本组件自身
 * 不接受 `readonly` —— 它一旦出现在 DOM 里就意味着「这条线程此刻可作答」。
 *
 * ⚠️ `options` 是后端 `JSONField(default=list)`、**schema 层零校验**：非 list 已在后端
 * 归一成 `[]`、非 dict 条目已丢弃，但每个键仍可能缺 ⇒ 逐项可选链取值再过滤空 label。
 *
 * 安全：候选项与输入内容全程走 Vue mustache 文本插值，不使用任何原始 HTML 注入指令。
 */

import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'

const props = withDefaults(defineProps<{
  /** 澄清线程的候选答案；点选即填入输入框，**仍可改写后再提交**。 */
  options?: Array<{ label?: string, value?: string, note?: string }>
  submitting?: boolean
  placeholder?: string
}>(), {
  options: () => [],
  submitting: false,
  placeholder: '',
})

const emit = defineEmits<{
  submit: [body: string]
}>()

const { t } = useI18n()

const body = ref('')

/** 逐项防御式取值：`label` 缺失时退回 `value`，两者都空的条目直接丢弃。 */
const normalizedOptions = computed(() =>
  (Array.isArray(props.options) ? props.options : [])
    .map((option, index) => {
      const label = String(option?.label ?? option?.value ?? '')
      return {
        key: `${index}-${label}`,
        label,
        value: String(option?.value ?? option?.label ?? ''),
        note: String(option?.note ?? ''),
      }
    })
    .filter(option => option.label.length > 0),
)

/** 空 / 纯空格一律不可提交（后端同样 400，双保险）。 */
const isEmpty = computed(() => body.value.trim().length === 0)
const canSubmit = computed(() => !isEmpty.value && !props.submitting)

function pickOption(value: string): void {
  body.value = value
}

function submit(): void {
  if (!canSubmit.value)
    return
  emit('submit', body.value.trim())
  body.value = ''
}
</script>

<template>
  <div data-testid="blueprint-thread-composer" class="space-y-2">
    <!-- 候选选项组：点选填入，不直接提交 -->
    <div v-if="normalizedOptions.length > 0" class="space-y-1.5">
      <p class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.thread.optionsHint') }}
      </p>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="option in normalizedOptions"
          :key="option.key"
          type="button"
          data-testid="blueprint-thread-option"
          class="rounded-full border border-border/60 bg-muted/40 px-2.5 py-1 text-xs text-foreground transition-colors hover:bg-muted"
          :title="option.note || option.label"
          @click="pickOption(option.value)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <Textarea
      v-model="body"
      data-testid="blueprint-thread-composer-input"
      class="min-h-20 text-sm"
      :placeholder="placeholder || t('knowledge.blueprints.thread.composerPlaceholder')"
    />

    <div class="flex items-center justify-between gap-2">
      <p v-if="isEmpty" class="text-xs text-destructive">
        {{ t('knowledge.blueprints.thread.composerEmpty') }}
      </p>
      <span v-else />
      <Button
        size="sm"
        data-testid="blueprint-thread-composer-submit"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ t('knowledge.blueprints.thread.composerSubmit') }}
      </Button>
    </div>
  </div>
</template>
