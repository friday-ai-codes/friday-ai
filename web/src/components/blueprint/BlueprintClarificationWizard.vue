<script setup lang="ts">
/**
 * 结构化澄清逐步向导（quick-260806-fy2）。
 *
 * 对齐飞书澄清卡精神：每题候选 + 「其他」+ 最后整包提交；Web 额外做成一题一题出现。
 * 输入必须是 `normalizeClarificationQuestions` 之后的题面；父层负责形状分流。
 *
 * 安全：题面 / 选项 / 功能点标题全程 Vue mustache，不使用任何原始 HTML 注入指令。
 */

import type { ClarificationQuestion } from '~/utils/clarificationQuestions'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
import {
  extractFeaturePointIds,
  formatClarificationAnswers,
} from '~/utils/clarificationQuestions'

const OTHER_VALUE = '__other__'

const props = withDefaults(defineProps<{
  questions: ClarificationQuestion[]
  /** 功能点 id → 标题；缺省时 chip 回退显示 id。 */
  featurePointTitles?: Record<string, string>
  submitting?: boolean
}>(), {
  featurePointTitles: () => ({}),
  submitting: false,
})

const emit = defineEmits<{
  submit: [body: string]
  'goto-anchor': [domId: string]
}>()

const { t } = useI18n()

const index = ref(0)
/** 每题：选中的选项值，或 OTHER_VALUE。 */
const selections = ref<string[]>([])
/** 每题「其他」自由文本。 */
const otherTexts = ref<string[]>([])

watch(
  () => props.questions,
  (list) => {
    const n = list.length
    selections.value = Array.from({ length: n }, (_, i) => selections.value[i] ?? '')
    otherTexts.value = Array.from({ length: n }, (_, i) => otherTexts.value[i] ?? '')
    if (index.value >= n)
      index.value = Math.max(0, n - 1)
  },
  { immediate: true },
)

const total = computed(() => props.questions.length)
const current = computed(() => props.questions[index.value] ?? null)
const isLast = computed(() => index.value >= total.value - 1)
const isFirst = computed(() => index.value <= 0)

const relatedIds = computed(() => {
  if (!current.value)
    return [] as string[]
  return extractFeaturePointIds(current.value.text, current.value.related_feature_points)
})

function titleOf(fpId: string): string {
  const title = String(props.featurePointTitles?.[fpId] ?? '').trim()
  return title || fpId
}

function pick(value: string): void {
  selections.value[index.value] = value
}

function answerOf(i: number): string {
  const selected = selections.value[i] ?? ''
  if (selected === OTHER_VALUE)
    return (otherTexts.value[i] ?? '').trim()
  return selected.trim()
}

const currentAnswerReady = computed(() => answerOf(index.value).length > 0)

const canSubmitAll = computed(() => {
  if (props.submitting || total.value === 0)
    return false
  return props.questions.every((_, i) => answerOf(i).length > 0)
})

function goPrev(): void {
  if (!isFirst.value)
    index.value -= 1
}

function goNext(): void {
  if (!currentAnswerReady.value)
    return
  if (!isLast.value) {
    index.value += 1
    return
  }
  submitAll()
}

function submitAll(): void {
  if (!canSubmitAll.value)
    return
  const pairs = props.questions.map((q, i) => ({
    question: q.text,
    answer: answerOf(i),
  }))
  emit('submit', formatClarificationAnswers(pairs))
}

function onGotoFp(fpId: string): void {
  emit('goto-anchor', `fp-${fpId}`)
}
</script>

<template>
  <div
    v-if="current"
    data-testid="blueprint-clarification-wizard"
    class="space-y-3"
  >
    <div class="flex items-center justify-between gap-2">
      <p class="text-xs font-medium text-muted-foreground" data-testid="blueprint-clarification-progress">
        {{ t('knowledge.blueprints.thread.wizardProgress', { i: index + 1, n: total }) }}
      </p>
      <Badge v-if="current.recommended" variant="info" class="shrink-0">
        {{ t('knowledge.blueprints.thread.wizardHasRecommended') }}
      </Badge>
    </div>

    <p class="text-sm leading-6 text-foreground" data-testid="blueprint-clarification-question">
      {{ current.text }}
    </p>

    <div v-if="relatedIds.length" class="space-y-1">
      <p class="text-[11px] text-muted-foreground">
        {{ t('knowledge.blueprints.thread.relatedFeaturePoints') }}
      </p>
      <div class="flex flex-wrap gap-1">
        <button
          v-for="fp in relatedIds"
          :key="fp"
          type="button"
          class="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-left text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
          data-testid="blueprint-clarification-fp-chip"
          :title="fp"
          @click="onGotoFp(fp)"
        >
          <span class="truncate">{{ titleOf(fp) }}</span>
          <span class="icon-[lucide--arrow-up-left] shrink-0 opacity-60" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-if="current.options.length" class="space-y-1.5">
      <p class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.thread.optionsHint') }}
      </p>
      <div class="flex flex-col gap-1.5" role="radiogroup">
        <button
          v-for="opt in current.options"
          :key="opt"
          type="button"
          role="radio"
          data-testid="blueprint-clarification-option"
          class="flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left text-xs leading-5 transition-colors"
          :class="selections[index] === opt
            ? 'border-primary bg-primary/5 text-foreground'
            : 'border-border/60 bg-muted/30 text-foreground hover:bg-muted/60'"
          :aria-checked="selections[index] === opt"
          @click="pick(opt)"
        >
          <span
            class="mt-0.5 size-3.5 shrink-0 rounded-full border"
            :class="selections[index] === opt ? 'border-primary bg-primary' : 'border-muted-foreground/40'"
            aria-hidden="true"
          />
          <span class="min-w-0 flex-1">
            {{ opt }}
            <Badge
              v-if="opt === current.recommended"
              variant="secondary"
              class="ml-1 align-middle"
              data-testid="blueprint-clarification-recommended"
            >
              {{ t('knowledge.blueprints.thread.recommended') }}
            </Badge>
          </span>
        </button>

        <button
          type="button"
          role="radio"
          data-testid="blueprint-clarification-other"
          class="flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left text-xs leading-5 transition-colors"
          :class="selections[index] === OTHER_VALUE
            ? 'border-primary bg-primary/5 text-foreground'
            : 'border-border/60 bg-muted/30 text-foreground hover:bg-muted/60'"
          :aria-checked="selections[index] === OTHER_VALUE"
          @click="pick(OTHER_VALUE)"
        >
          <span
            class="mt-0.5 size-3.5 shrink-0 rounded-full border"
            :class="selections[index] === OTHER_VALUE ? 'border-primary bg-primary' : 'border-muted-foreground/40'"
            aria-hidden="true"
          />
          <span>{{ t('knowledge.blueprints.thread.wizardOther') }}</span>
        </button>
      </div>
    </div>

    <Textarea
      v-if="!current.options.length || selections[index] === OTHER_VALUE"
      v-model="otherTexts[index]"
      data-testid="blueprint-clarification-other-input"
      class="min-h-20 text-sm"
      :placeholder="current.options.length
        ? t('knowledge.blueprints.thread.wizardOtherPlaceholder')
        : t('knowledge.blueprints.thread.composerPlaceholder')"
    />

    <div class="flex items-center justify-between gap-2 pt-0.5">
      <Button
        type="button"
        size="sm"
        variant="ghost"
        data-testid="blueprint-clarification-prev"
        :disabled="isFirst || submitting"
        @click="goPrev"
      >
        {{ t('knowledge.blueprints.thread.wizardPrev') }}
      </Button>
      <Button
        type="button"
        size="sm"
        data-testid="blueprint-clarification-next"
        :disabled="isLast ? !canSubmitAll : !currentAnswerReady || submitting"
        @click="goNext"
      >
        {{ isLast
          ? t('knowledge.blueprints.thread.wizardSubmitAll')
          : t('knowledge.blueprints.thread.wizardNext') }}
      </Button>
    </div>
  </div>
</template>
