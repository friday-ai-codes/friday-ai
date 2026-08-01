<script setup lang="ts">
/**
 * 侧栏单条线程卡（Phase 115-04，UI-SPEC §7.7 / §7.8 / §7.9 / §18.1）。
 *
 * ⭐ **本组件是 114-REVIEW CR-01 在 UI 上的落点，也是本相位最不能做错的一条。**
 * 动作区按 `kind` **在渲染层硬分流**，两条分支在模板里物理互斥（`v-if` / `v-else`）：
 *
 * | kind | 渲染的动作 | 端点 |
 * |---|---|---|
 * | `ai_review_finding` | 只有 `BlueprintFindingActions`（已修复 / 误报忽略，各自必填理由） | `resolve/` · `dismiss/` |
 * | `ai_clarification` / `human_comment` / `repo_confirmation` | 只有 `BlueprintThreadComposer` | `answer/` |
 *
 * **理由（不可妥协）**：114 对 finding 走 `answer` 通道**一律 400**，且回灌链
 * `REFLOW_KINDS` fail-closed 过滤。UI 若给统一输入框再按 kind 切端点，必然稳定撞 400
 * 或误处置（在 BLOCKER 上回一句任意文本就把确认门解开）。所以分流做在**渲染层**
 * ——压根不给错的入口——而不是提交层。⛔ 不是 `disabled`、⛔ 不是 `v-show`。
 *
 * ⭐ **两种「不可用」刻意不同**：
 * - 作答框受可编辑闸约束，且形态是**不存在于 DOM**（`v-if="!readonly"`，§7.9）；
 * - finding 处置**不受该闸约束**（后端未对 `resolve/` `dismiss/` 加状态闸，且那是超界
 *   死锁的唯一正向出口）—— `readonly === true` 时它仍然渲染。
 *
 * ⭐ **失锚线程仍可回复 / 处置**：`anchor_status === 'orphaned'` 只影响「正文能不能定位」
 * （卡内改为展示引用时的原文快照），⛔ 不 disable 任何动作。
 *
 * a11y（§18.1）：卡片的**选中区**是 `<button data-testid="blueprint-thread-card-select">`
 * （可 Tab、`Enter`/`Space` 选中；侧栏的 `↑`/`↓` 也按它移动焦点）。它是 §18.3 点名的四个
 * 新增焦点目标之一 ⇒ 焦点环取 `annotationTokens` 里那份共用的 `FOCUS_RING_CLASS`
 * （不透明 `--color-primary-600`，3.74:1），⛔ 不各写一串、⛔ 不沿用既有那个半透明值。
 * ⚠️ 交互控件（作答框、处置按钮）与长正文（消息列表、引文快照）**放在该 `<button>` 之外**
 * —— 表单控件嵌进 button 是非法 DOM 且点击会连带触发外层按钮；`<ul>` / `<pre>` 也不是
 * button 允许的内容模型。选中区与内容区因此拆成兄弟节点，卡根仍是
 * `data-testid="blueprint-thread-card"` 的容器（测试与计数按它定位）。
 *
 * 安全：消息正文、`quoted_text` 全程 Vue mustache + `<pre>`，不使用任何原始 HTML 注入指令。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { FOCUS_RING_CLASS } from './annotationTokens'
import BlueprintFindingActions from './BlueprintFindingActions.vue'
import BlueprintThreadComposer from './BlueprintThreadComposer.vue'

const props = withDefaults(defineProps<{
  thread: BlueprintThreadDetail
  active?: boolean
  /** 可编辑闸（`isBlueprintEditable(current_status) === false` ⇒ `true`），由父层算好传入。 */
  readonly?: boolean
  submitting?: boolean
  /**
   * 越界降级标记：判据是 115-02 的 `isValidAnchor(anchor, blockText.length)`，
   * 需要块正文才能算 ⇒ 由持有正文的父层判定后传入（本组件只拿到线程）。
   */
  degraded?: boolean
  /** 确认门面板是否存在；⭐ 面板缺席时「前往确认门」链接不渲染。 */
  gateAvailable?: boolean
}>(), {
  active: false,
  readonly: false,
  submitting: false,
  degraded: false,
  gateAvailable: false,
})

const emit = defineEmits<{
  'select': [threadId: string]
  'answer': [threadId: string, body: string]
  'resolve': [threadId: string, reason: string]
  'dismiss': [threadId: string, reason: string]
  'goto-gate': [threadId: string]
}>()

const { t } = useI18n()

const KIND_LABEL_KEY: Record<string, string> = {
  ai_clarification: 'kindAiClarification',
  ai_review_finding: 'kindAiReviewFinding',
  human_comment: 'kindHumanComment',
  repo_confirmation: 'kindRepoConfirmation',
}

const SEVERITY_LABEL_KEY: Record<string, string> = {
  'blocker': 'severityBlocker',
  'warning': 'severityWarning',
  'info': 'severityInfo',
  '': 'severityNone',
}

/** severity → Badge variant（⛔ 不用 `:class` 追加颜色类）。 */
const SEVERITY_VARIANT: Record<string, 'destructive' | 'warning' | 'info' | 'muted'> = {
  'blocker': 'destructive',
  'warning': 'warning',
  'info': 'info',
  '': 'muted',
}

const STATUS_LABEL_KEY: Record<string, string> = {
  open: 'groupOpen',
  answered: 'groupAnswered',
  resolved: 'groupClosed',
  dismissed: 'groupClosed',
}

const STATUS_VARIANT: Record<string, 'outline' | 'info' | 'muted'> = {
  open: 'outline',
  answered: 'info',
  resolved: 'muted',
  dismissed: 'muted',
}

/**
 * ⭐ finding 判据（唯一一处），模板据它做两条互斥分支。
 * ⛔ 不要改成「统一渲染 + 提交时按 kind 切端点」——那是 CR-01 明令禁止的形态。
 */
const isFinding = computed(() => props.thread.kind === 'ai_review_finding')

const isOrphaned = computed(() => props.thread.anchor_status === 'orphaned')

const kindLabel = computed(() =>
  t(`knowledge.blueprints.thread.${KIND_LABEL_KEY[props.thread.kind] ?? 'kindHumanComment'}`),
)
const severityLabel = computed(() =>
  t(`knowledge.blueprints.thread.${SEVERITY_LABEL_KEY[props.thread.severity] ?? 'severityNone'}`),
)
const severityVariant = computed(() => SEVERITY_VARIANT[props.thread.severity] ?? 'muted')
const statusLabel = computed(() =>
  t(`knowledge.blueprints.thread.${STATUS_LABEL_KEY[props.thread.status] ?? 'groupOpen'}`),
)
const statusVariant = computed(() => STATUS_VARIANT[props.thread.status] ?? 'outline')

const quotedText = computed(() => String(props.thread.anchor?.quoted_text ?? ''))

/** 确认门线程才给「前往确认门」入口，且面板必须存在（目标面板归 115-07）。 */
const showGateLink = computed(() =>
  props.thread.kind === 'repo_confirmation' && props.gateAvailable,
)

/**
 * ⚠️ 仓内无共享的相对时间工具，`knowledge.blueprints.*` 也没有相对时间单位文案键，
 * 而 i18n 三处追加点已在 115-02 对本相位关闭 ⇒ 退化为本地化的绝对时间（回报而不自补）。
 */
function formatTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('zh-CN', { hour12: false })
}

function authorLabel(authorType: string, display: string): string {
  if (display)
    return display
  return authorType === 'ai' ? t('knowledge.blueprints.thread.authorAi') : '—'
}

function onSelect(): void {
  emit('select', props.thread.thread_id)
}

function onAnswer(body: string): void {
  emit('answer', props.thread.thread_id, body)
}

function onResolve(threadId: string, reason: string): void {
  emit('resolve', threadId, reason)
}

function onDismiss(threadId: string, reason: string): void {
  emit('dismiss', threadId, reason)
}

function onGotoGate(): void {
  emit('goto-gate', props.thread.thread_id)
}
</script>

<template>
  <div
    data-testid="blueprint-thread-card"
    :data-thread-id="thread.thread_id"
    :data-thread-kind="thread.kind"
    :data-thread-status="thread.status"
    :data-anchor-status="thread.anchor_status"
    class="rounded-xl border border-border/60 bg-card p-3 space-y-2.5"
    :class="active ? 'ring-2 ring-primary/60' : ''"
  >
    <!-- 选中区（头部摘要）：可点 / 可聚焦；⛔ 内部不放表单控件与长正文 -->
    <button
      type="button"
      data-testid="blueprint-thread-card-select"
      class="flex w-full flex-wrap items-center gap-1.5 rounded-md text-left"
      :class="FOCUS_RING_CLASS"
      :aria-pressed="active"
      @click="onSelect"
    >
      <Badge variant="secondary">
        {{ kindLabel }}
      </Badge>
      <Badge :variant="severityVariant">
        {{ severityLabel }}
      </Badge>
      <Badge :variant="statusVariant">
        {{ statusLabel }}
      </Badge>
      <span class="ml-auto text-[11px] text-muted-foreground">{{ formatTime(thread.created_at) }}</span>
    </button>

    <!-- 失锚：原文已变更，只能给引用时的快照 -->
    <p v-if="isOrphaned" data-testid="blueprint-thread-orphaned" class="text-xs text-muted-foreground">
      {{ t('knowledge.blueprints.annotation.orphaned') }}
    </p>
    <!-- 越界降级：能定位到块但定位不到片段 -->
    <p v-else-if="degraded" data-testid="blueprint-thread-degraded" class="text-xs text-muted-foreground">
      {{ t('knowledge.blueprints.annotation.degraded') }}
    </p>

    <div v-if="quotedText" class="rounded-lg bg-muted/50 px-2.5 py-1.5">
      <p class="text-[11px] text-muted-foreground">
        {{ t('knowledge.blueprints.annotation.quotedSnapshot') }}
      </p>
      <pre class="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-foreground">{{ quotedText }}</pre>
    </div>

    <!-- 多轮消息（`author_display` 可能是空串：作者是 AI 或已被删） -->
    <ul v-if="thread.messages.length > 0" class="space-y-2">
      <li
        v-for="message in thread.messages"
        :key="message.id"
        data-testid="blueprint-thread-message"
        class="space-y-0.5"
      >
        <div class="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Badge :variant="message.author_type === 'ai' ? 'info' : 'secondary'">
            {{ authorLabel(message.author_type, message.author_display) }}
          </Badge>
          <span>{{ formatTime(message.created_at) }}</span>
        </div>
        <pre class="whitespace-pre-wrap break-words text-xs leading-5 text-foreground">{{ message.body }}</pre>
      </li>
    </ul>

    <p v-if="thread.last_reminded_at" class="text-[11px] text-muted-foreground">
      {{ t('knowledge.blueprints.thread.reminded', { time: formatTime(thread.last_reminded_at) }) }}
    </p>

    <!-- ⭐ 动作区：按 kind 硬分流，两条分支物理互斥 -->
    <div v-if="isFinding" class="pt-0.5">
      <BlueprintFindingActions
        :thread-id="thread.thread_id"
        :submitting="submitting"
        @resolve="onResolve"
        @dismiss="onDismiss"
      />
    </div>
    <div v-else class="space-y-2 pt-0.5">
      <BlueprintThreadComposer
        v-if="!readonly"
        :options="thread.options"
        :submitting="submitting"
        @submit="onAnswer"
      />
      <Button
        v-if="showGateLink"
        size="sm"
        variant="link"
        data-testid="blueprint-thread-goto-gate"
        @click="onGotoGate"
      >
        {{ t('knowledge.blueprints.thread.gotoGate') }}
      </Button>
    </div>
  </div>
</template>
