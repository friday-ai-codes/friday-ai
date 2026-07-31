<script setup lang="ts">
/**
 * 决策记录段（Phase 115-05，UI-SPEC §6.1 段 8）+ 段尾的 `deferred_ideas` 折叠区。
 *
 * ⭐ **本段同样不接批注层、不收 blockCtx**（与验收锚点段同一理由，P-14）：
 * `decision_log` / `deferred_ideas` **都不在** `iter_blocks` 的走查范围里 ⇒ 零 `block_id` ⇒
 * 后端不会往这两处挂线程。给它们接上批注层只会得到死码，还会误导用户以为能在此划线。
 *
 * ⚠️ **两者都是「零 items 约束的裸 array」**（`blueprint_schema.py:733-744`：只声明
 * `{"type": "array", "description": ...}`，**无 `items`**，且都不在顶层 `required`）⇒ 条目形状
 * 运行期什么都有可能。114-04 写入的 `{thread_id, question, answer, decision, decided_by,
 * decided_at, applied_in_version}` 是**约定不是契约** ⇒ 全程逐键收窄，缺键渲染「—」，
 * ⛔ 不渲染 `undefined`、⛔ 不抛。特别保 `answer` 键 —— 它是唯一有下游消费方的键
 * （`blueprint_spec_gate._collect_prior_answers` 读它）。
 *
 * ⭐ **`open-thread` 的语义由本 plan 定夺 = 「跳转到该决策对应的线程」**（⛔ 不是「在本段发起
 * 批注」）：条目带 `thread_id` 时才渲染入口按钮并 emit 它；不带则**不渲染**该按钮
 * —— 渲染一个点了没反应的按钮比不渲染更糟。
 *
 * ⛔ **`execution_plan` 本段不渲染**（CONTEXT `<deferred>` 已登记）：它是确认后确定性派生的
 * 执行计划，呈现面归属实施链路（116+）；在只读评审面渲染它会与 `TechPlanCard`（§13.2 禁区）
 * 职责重叠，越过本相位的并行边界。
 *
 * **分工边界（P-4）**：`<section id="decision_log">` 容器与导航项由页面无条件渲染，
 * 本组件只决定段内出不出内容。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补，见 115-05-SUMMARY §i18n）**：决策条目的字段标签、
 * 「查看对应线程」与「本方案明确不做的事（{n}）」都无键 ⇒ 条目改用**结构表达**（提问作标题、
 * 答案作正文、结论作徽标，身份走 `data-field`），跳转入口复用 `annotation.sidebarToggleEmpty`
 * （批注）+ 图标，折叠组头渲染 schema 原样键名 + 条数徽标。
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'

const props = withDefaults(defineProps<{
  /** 零 items 约束的裸 array ⇒ `unknown[]`，⛔ 不假设条目形状。 */
  decisionLog?: unknown[]
  deferredIdeas?: unknown[]
}>(), {
  decisionLog: () => [],
  deferredIdeas: () => [],
})

const emit = defineEmits<{
  /** ⭐ 语义 = 跳转到该决策对应的线程（⛔ 不是在本段发起批注）。 */
  'open-thread': [threadId: string]
}>()

const { t } = useI18n()

/** 缺键占位符（⛔ 不渲染 `undefined`）。 */
const PLACEHOLDER = '—'

function text(bag: Record<string, unknown>, key: string): string {
  const value = bag[key]
  if (typeof value === 'string' && value)
    return value
  if (typeof value === 'number' && Number.isFinite(value))
    return String(value)
  return PLACEHOLDER
}

/** 时间格式化：非法值原样显示（⛔ 不抛、⛔ 不吞成空）。 */
function formatTime(raw: unknown): string {
  if (typeof raw !== 'string' || !raw)
    return PLACEHOLDER
  const date = new Date(raw)
  if (Number.isNaN(date.getTime()))
    return raw
  return date.toLocaleString('zh-CN', { hour12: false })
}

const decisions = computed(() => {
  const list = Array.isArray(props.decisionLog) ? props.decisionLog : []
  return list.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>
    const threadId = typeof item.thread_id === 'string' && item.thread_id ? item.thread_id : ''
    return {
      key: `${index}`,
      threadId,
      question: text(item, 'question'),
      // ⭐ `answer` 是唯一有下游消费方的键，必须显式渲染。
      answer: text(item, 'answer'),
      decision: text(item, 'decision'),
      decidedBy: text(item, 'decided_by'),
      decidedAt: formatTime(item.decided_at),
      appliedInVersion: typeof item.applied_in_version === 'string' && item.applied_in_version
        ? item.applied_in_version
        : '',
    }
  })
})

const deferred = computed(() => {
  const list = Array.isArray(props.deferredIdeas) ? props.deferredIdeas : []
  return list.map((raw, index) => {
    if (typeof raw === 'string')
      return { key: `${index}`, text: raw || PLACEHOLDER }
    const item = (raw ?? {}) as Record<string, unknown>
    const value = text(item, 'text')
    return { key: `${index}`, text: value === PLACEHOLDER ? text(item, 'idea') : value }
  })
})
</script>

<template>
  <div data-testid="blueprint-decision-log" class="space-y-4">
    <CompactEmptyState
      v-if="!decisions.length && !deferred.length"
      icon="lucide--file-text"
      :title="t('knowledge.blueprints.sectionEmpty', { name: t('knowledge.blueprints.section.decisionLog') })"
    />

    <div
      v-for="entry in decisions"
      :key="entry.key"
      class="card space-y-1.5 p-4"
      data-testid="blueprint-decision-entry"
    >
      <div class="flex items-start gap-2">
        <p class="min-w-0 flex-1 text-sm font-medium" data-field="question">
          {{ entry.question }}
        </p>
        <!-- ⭐ thread_id 存在才渲染跳转入口 -->
        <button
          v-if="entry.threadId"
          type="button"
          class="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-primary"
          data-testid="blueprint-decision-goto-thread"
          @click="emit('open-thread', entry.threadId)"
        >
          <span class="icon-[lucide--message-square-dot]" aria-hidden="true" />
          <span>{{ t('knowledge.blueprints.annotation.sidebarToggleEmpty') }}</span>
        </button>
      </div>

      <p class="text-sm leading-relaxed text-muted-foreground" data-field="answer">
        {{ entry.answer }}
      </p>

      <div class="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <Badge variant="outline" data-field="decision">
          {{ entry.decision }}
        </Badge>
        <span data-field="decided-by">{{ entry.decidedBy }}</span>
        <span data-field="decided-at">{{ entry.decidedAt }}</span>
        <Badge v-if="entry.appliedInVersion" variant="muted" data-field="applied-in-version">
          {{ entry.appliedInVersion }}
        </Badge>
      </div>
    </div>

    <!-- 段尾：deferred_ideas 默认折叠（空则整块不渲染） -->
    <Collapsible v-if="deferred.length" data-testid="blueprint-deferred-ideas">
      <CollapsibleTrigger class="flex w-full items-center gap-1.5 rounded-lg py-1 text-left text-xs font-medium text-muted-foreground hover:text-foreground">
        <span class="icon-[lucide--chevron-right]" aria-hidden="true" />
        <span class="font-mono">deferred_ideas</span>
        <Badge variant="muted">
          {{ deferred.length }}
        </Badge>
      </CollapsibleTrigger>
      <CollapsibleContent class="pt-1.5">
        <ul class="space-y-1">
          <li
            v-for="idea in deferred"
            :key="idea.key"
            class="text-sm text-muted-foreground"
            data-testid="blueprint-deferred-idea"
          >
            {{ idea.text }}
          </li>
        </ul>
      </CollapsibleContent>
    </Collapsible>
  </div>
</template>
