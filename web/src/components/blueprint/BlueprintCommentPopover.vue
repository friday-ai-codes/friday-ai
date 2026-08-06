<script setup lang="ts">
/**
 * 划线评论就地浮层（quick-260806-j1z，交互对齐飞书文档）。
 *
 * 两种互斥模式（由传入的 props 决定）：
 * - **draft**：选区「发起评论」后浮出的评论输入卡（引用条 + 输入框 + 发送）；
 *   Enter 发送、Shift+Enter 换行（飞书文档同款）。
 * - **thread**：点击正文划线后浮出的线程卡 —— 内嵌 `BlueprintThreadCard`，
 *   动作分流（评论作答 / finding 处置 / 澄清向导）全部沿用其 kind 硬分流，
 *   ⛔ 本组件不发明任何新动作入口（resolve/dismiss 后端仅对 finding 开放）。
 *
 * 定位：打开瞬间把 viewport 矩形换算成**文档坐标**（+ scrollX/Y），Teleport 到 body
 * 后 `position: absolute` ⇒ 卡片随文档滚动（飞书评论卡同款贴文行为），无需滚动监听。
 * 左右用视口宽夹取，垂直落在锚点矩形下方 8px。
 *
 * 关闭：点外（onClickOutside）与 Esc 都 emit `close`，由父层清状态；
 * ⛔ 组件自身不持有开合状态（受控组件，出现即打开）。
 *
 * 安全：引用条与输入内容全程 mustache 文本插值。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'
import { onClickOutside, useEventListener } from '@vueuse/core'
import { computed, nextTick, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'
import { Textarea } from '~/components/ui/textarea'
import BlueprintThreadCard from './BlueprintThreadCard.vue'

const props = withDefaults(defineProps<{
  /** 锚点矩形（viewport 坐标，打开时换算为文档坐标）。 */
  rect: DOMRect
  /** draft 模式：被评论的原文引用。 */
  quotedText?: string
  /** thread 模式：要展示的线程。 */
  thread?: BlueprintThreadDetail | null
  readonly?: boolean
  submitting?: boolean
  gateAvailable?: boolean
  featurePointTitles?: Record<string, string>
}>(), {
  quotedText: '',
  thread: null,
  readonly: false,
  submitting: false,
  gateAvailable: false,
  featurePointTitles: () => ({}),
})

const emit = defineEmits<{
  'submit': [body: string]
  'close': []
  'answer': [threadId: string, body: string]
  'resolve': [threadId: string, reason: string]
  'dismiss': [threadId: string, reason: string]
  'goto-gate': [threadId: string]
  'goto-anchor': [domId: string]
}>()

const { t } = useI18n()

const CARD_WIDTH = 360
const VIEWPORT_MARGIN = 16

const isDraft = computed(() => !props.thread)

/** 打开瞬间换算一次文档坐标；此后随文档滚动，⛔ 不做滚动重定位。 */
const positionStyle = computed(() => {
  const viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth
  const scrollX = typeof window === 'undefined' ? 0 : window.scrollX
  const scrollY = typeof window === 'undefined' ? 0 : window.scrollY
  const left = Math.min(
    Math.max(props.rect.left + scrollX, VIEWPORT_MARGIN),
    Math.max(viewportWidth - CARD_WIDTH - VIEWPORT_MARGIN + scrollX, VIEWPORT_MARGIN),
  )
  return {
    position: 'absolute' as const,
    top: `${props.rect.bottom + scrollY + 8}px`,
    left: `${left}px`,
    width: `${CARD_WIDTH}px`,
  }
})

const cardEl = ref<HTMLElement | null>(null)
const body = ref('')

const canSubmit = computed(() => body.value.trim().length > 0 && !props.submitting)

function submit(): void {
  if (!canSubmit.value)
    return
  emit('submit', body.value.trim())
  body.value = ''
}

onClickOutside(cardEl, () => emit('close'))
useEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key === 'Escape')
    emit('close')
})

onMounted(() => {
  if (isDraft.value) {
    nextTick(() => {
      const el = cardEl.value?.querySelector<HTMLTextAreaElement>('textarea')
      el?.focus()
    })
  }
})
</script>

<template>
  <Teleport to="body">
    <div
      ref="cardEl"
      data-testid="blueprint-comment-popover"
      :data-popover-mode="isDraft ? 'draft' : 'thread'"
      class="z-40 rounded-xl border border-border/60 bg-card shadow-lg"
      :style="positionStyle"
      role="dialog"
      :aria-label="isDraft
        ? t('knowledge.blueprints.annotation.inlineComposer.title')
        : t('knowledge.blueprints.annotation.sidebarTitle')"
    >
      <!-- draft：飞书式评论输入卡 -->
      <div v-if="isDraft" class="space-y-2.5 p-3">
        <div
          v-if="quotedText"
          class="border-l-2 border-warning/70 bg-muted/40 px-2.5 py-1.5"
          data-testid="blueprint-comment-quote"
        >
          <p class="line-clamp-2 text-xs leading-5 text-muted-foreground">
            {{ quotedText }}
          </p>
        </div>
        <Textarea
          v-model="body"
          data-testid="blueprint-comment-input"
          class="min-h-16 text-sm"
          :placeholder="t('knowledge.blueprints.annotation.inlineComposer.placeholder')"
          @keydown.enter.exact.prevent="submit"
        />
        <div class="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            data-testid="blueprint-comment-cancel"
            @click="emit('close')"
          >
            {{ t('knowledge.blueprints.annotation.inlineComposer.cancel') }}
          </Button>
          <Button
            size="sm"
            data-testid="blueprint-comment-send"
            :disabled="!canSubmit"
            @click="submit"
          >
            {{ t('knowledge.blueprints.annotation.inlineComposer.send') }}
          </Button>
        </div>
      </div>

      <!-- thread：就地线程卡（动作分流全部沿用 BlueprintThreadCard） -->
      <div v-else class="max-h-[65vh] overflow-y-auto p-1.5">
        <BlueprintThreadCard
          v-if="thread"
          :thread="thread"
          active
          :readonly="readonly"
          :submitting="submitting"
          :gate-available="gateAvailable"
          :feature-point-titles="featurePointTitles"
          @answer="(id, text) => emit('answer', id, text)"
          @resolve="(id, reason) => emit('resolve', id, reason)"
          @dismiss="(id, reason) => emit('dismiss', id, reason)"
          @goto-gate="emit('goto-gate', $event)"
          @goto-anchor="emit('goto-anchor', $event)"
        />
      </div>
    </div>
  </Teleport>
</template>
