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
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { isKnownFindingRule, parseFindingBody } from '~/utils/blueprintFindingRules'
import {
  extractFeaturePointIds,
  isStructuredClarificationQuestions,
  normalizeClarificationQuestions,
  parseClarificationAnswers,
} from '~/utils/clarificationQuestions'
import { parseBlueprintSectionPath, resolveBlueprintAnchorDomId } from './anchorTargets'
import { FOCUS_RING_CLASS } from './annotationTokens'
import BlueprintClarificationWizard from './BlueprintClarificationWizard.vue'
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
  /** 功能点 id → 标题；结构化澄清向导 chip 展示用。 */
  featurePointTitles?: Record<string, string>
  /** 仓库 id → 仓名；段级 finding 的位置入口展示用。 */
  repoNames?: Record<string, string>
  /**
   * 是否渲染 kind 徽标。侧栏已按 kind 分组，组内每张卡再挂一枚同名徽标是纯冗余
   * （quick-260806-tsb 视觉整改）⇒ 侧栏传 `false`；就地浮层（CommentPopover）无分组
   * 语境，保持默认 `true`。
   */
  showKind?: boolean
}>(), {
  active: false,
  readonly: false,
  submitting: false,
  degraded: false,
  gateAvailable: false,
  featurePointTitles: () => ({}),
  repoNames: () => ({}),
  showKind: true,
})

const emit = defineEmits<{
  'select': [threadId: string]
  'answer': [threadId: string, body: string]
  'resolve': [threadId: string, reason: string]
  'dismiss': [threadId: string, reason: string]
  'goto-gate': [threadId: string]
  'goto-anchor': [domId: string]
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

/** 已有结论的线程（resolved / dismissed）不再渲染作答框 —— 对着已关闭的问题挂一个
 * 输入框只会诱导无意义的追答（116 视觉整改；后端虽允许追加消息，但那不是主路径）。 */
const isClosed = computed(
  () => props.thread.status === 'resolved' || props.thread.status === 'dismissed',
)

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
const sectionPath = computed(() =>
  typeof props.thread.anchor?.section_path === 'string'
    ? props.thread.anchor.section_path.trim()
    : '',
)
const hasBlockAnchor = computed(() =>
  typeof props.thread.anchor?.block_id === 'string' && Boolean(props.thread.anchor.block_id.trim()),
)
const anchorTarget = computed(() => parseBlueprintSectionPath(sectionPath.value))
const anchorDomId = computed(() => resolveBlueprintAnchorDomId(props.thread.anchor))

const SECTION_LABEL_KEY: Record<string, string> = {
  requirement_spec: 'requirementSpec',
  repo_associations: 'repoAssociations',
  current_state_analysis: 'currentStateAnalysis',
  implementation_overview: 'implementationOverview',
  api_contracts: 'apiContracts',
  impact_analysis: 'impactAnalysis',
  interaction_flows: 'interactionFlows',
  must_haves: 'mustHaves',
  decision_log: 'decisionLog',
  associations: 'associations',
}

const REPO_FIELD_LABEL_KEY: Record<string, string> = {
  responsibility: 'responsibility',
  rationale: 'rationale',
  fitness: 'fitness',
  planned_change_summary: 'plannedChange',
  support_needed: 'supportNeeded',
  capabilities_used: 'capabilitiesUsed',
}

/** 段级 finding 的人读位置；未知字段保留原路径，避免静默吞掉定位线索。 */
const anchorLocationLabel = computed(() => {
  const target = anchorTarget.value
  if (!target)
    return sectionPath.value

  if (target.kind === 'repo') {
    const repoName = props.repoNames[target.itemId] || t('knowledge.blueprints.activity.repoUnknown')
    const field = target.fieldPath.split('.')[0] ?? ''
    const fieldKey = REPO_FIELD_LABEL_KEY[field]
    return fieldKey
      ? `${repoName} · ${t(`knowledge.blueprints.repo.${fieldKey}`)}`
      : `${repoName} · ${sectionPath.value}`
  }

  const sectionLabelKey = SECTION_LABEL_KEY[target.sectionKey]
  const sectionLabel = sectionLabelKey
    ? t(`knowledge.blueprints.section.${sectionLabelKey}`)
    : target.sectionKey
  return target.itemId ? `${sectionLabel} · ${target.itemId}` : sectionLabel
})

const showAnchorLocation = computed(() =>
  !isOrphaned.value
  && !quotedText.value
  && !hasBlockAnchor.value
  && Boolean(sectionPath.value)
  && Boolean(anchorDomId.value)
  && Boolean(anchorLocationLabel.value),
)

/**
 * 等待态（Phase 117，WAIT-03）。
 *
 * ⭐ **「已到期」不是线程状态**：后端到期只停提醒，`status` 仍是 `open`、`blocking` 仍为
 * true（否则超时就等于自动放行未决澄清）。所以这里把它渲染成一个**独立徽标 + 说明**，
 * ⛔ 不塞进 `STATUS_LABEL_KEY` 那张表 —— 混进状态标签会让人以为这条已经处置完了。
 *
 * 未决线程才展示等待信息：已作答/已关闭的线程「等了多久」没有意义。
 */
const isExpired = computed(() => Boolean(props.thread.expired_at) && props.thread.status === 'open')

const reminderCount = computed(() => Number(props.thread.reminder_count ?? 0))

/** 等待天数（向下取整；不足一天不展示，避免出现「已等待 0 天」）。 */
const waitingDays = computed(() => {
  if (isClosed.value || props.thread.status === 'answered')
    return 0
  const created = new Date(props.thread.created_at).getTime()
  if (Number.isNaN(created))
    return 0
  return Math.floor((Date.now() - created) / 86400000)
})

/**
 * 确认门线程才给「前往确认门」入口，且面板必须存在（目标面板归 115-07）。
 *
 * ⭐ quick-260806 视觉整改：面板可用时本卡**不再渲染作答框** —— 确认门的权威交互面是
 * 正文顶部的面板（移除/加仓/改判/确认都在那里），侧栏再挂一个自由文本问答框只会让人
 * 在错误的入口回复（用户实测点名的「右侧问答式看不出实际内容」）。面板缺席（已锁定 /
 * 快照读不到）时保留作答框作为兜底，避免把线程堵死。
 */
const showGateLink = computed(() =>
  props.thread.kind === 'repo_confirmation' && props.gateAvailable,
)

/**
 * ⭐ 规格门结构化澄清：`options` 存的是 `{text, options[]}` 题面，不是扁平候选。
 * 有结构化题时走逐步向导，并隐藏首条 AI 编号题面（避免与向导重复）。
 */
const structuredQuestions = computed(() =>
  isStructuredClarificationQuestions(props.thread.options)
    ? normalizeClarificationQuestions(props.thread.options)
    : [],
)

const useClarificationWizard = computed(() => structuredQuestions.value.length > 0)

/** 旧 composer 只认扁平 `{label,value,note}`；结构化题项在此过滤掉（类型双形态见 types/blueprint.ts）。 */
const flatOptions = computed(() =>
  (Array.isArray(props.thread.options) ? props.thread.options : []).filter(
    (opt): opt is { label?: string, value?: string, note?: string } =>
      Boolean(opt) && typeof opt === 'object' && !('text' in opt) && !('question' in opt),
  ),
)

// ── 已答/已关闭澄清的问答对视图（quick-260806 视觉整改）─────────────────────────
//
// 作答正文是 `formatClarificationAnswers` 拼的 `N. 题面\n→ 答案`，整墙 `pre` 不便查阅；
// 解析回问答对，逐题渲染「题面 + 答案 + 功能点跳转 chips」。解析不出即回退原始消息。

/** 最后一条可解析出编号答案的人工消息（找不到 ⇒ 问答对视图不启用）。 */
const answerSource = computed(() => {
  if (!structuredQuestions.value.length)
    return null
  const messages = props.thread.messages ?? []
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index]
    if (message.author_type === 'ai')
      continue
    const answers = parseClarificationAnswers(String(message.body ?? ''))
    if (answers.size)
      return { message, answers }
  }
  return null
})

/** 问答对：题序 1-based 与作答编号对齐；答案缺席的题渲染题面不渲染箭头行。 */
const qaPairs = computed(() => {
  const source = answerSource.value
  if (!source)
    return []
  return structuredQuestions.value.map((question, index) => ({
    no: index + 1,
    text: question.text,
    answer: source.answers.get(index + 1) ?? '',
    fpIds: extractFeaturePointIds(question.text, question.related_feature_points),
  }))
})

const showQaView = computed(() => qaPairs.value.length > 0)

/** 问答对展开态（默认收起：题面 2 行 / 答案 3 行截断）。 */
const qaExpanded = ref(false)

function titleOf(fpId: string): string {
  return props.featurePointTitles[fpId] || fpId
}

// ── 长消息折叠（超过阈值默认 6 行截断，可展开）────────────────────────────────

const MESSAGE_CLAMP_CHARS = 320

const expandedMessageIds = ref(new Set<string | number>())

function isMessageClamped(id: string | number, text: string): boolean {
  return text.length > MESSAGE_CLAMP_CHARS && !expandedMessageIds.value.has(id)
}

function isMessageExpandable(text: string): boolean {
  return text.length > MESSAGE_CLAMP_CHARS
}

function toggleMessage(id: string | number): void {
  const next = new Set(expandedMessageIds.value)
  if (next.has(id))
    next.delete(id)
  else
    next.add(id)
  expandedMessageIds.value = next
}

/** 结构化向导 / 问答对视图已承载题面时，跳过首条 AI 编号题面；问答对视图同时收起作答原文。 */
const visibleMessages = computed(() => {
  const messages = props.thread.messages ?? []
  const hideFirstAi = useClarificationWizard.value || showQaView.value
  const answerMessageId = showQaView.value ? answerSource.value?.message.id : null
  return messages.filter((message, messageIndex) => {
    if (hideFirstAi && messageIndex === 0 && message.author_type === 'ai')
      return false
    if (answerMessageId != null && message.id === answerMessageId)
      return false
    return true
  })
})

interface MessageTextSegment {
  type: 'text' | 'repository'
  text: string
  repositoryId?: string
}

const REPOSITORY_UUID_PATTERN = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi

/** 把线程正文中的仓库 UUID 转成可读、可跳转的仓库标签。 */
function repoAwareSegments(text: string): MessageTextSegment[] {
  const segments: MessageTextSegment[] = []
  let cursor = 0
  for (const match of text.matchAll(REPOSITORY_UUID_PATTERN)) {
    const index = match.index ?? 0
    if (index > cursor)
      segments.push({ type: 'text', text: text.slice(cursor, index) })
    const repositoryId = match[0]
    segments.push({
      type: 'repository',
      repositoryId,
      text: props.repoNames[repositoryId] || t('knowledge.blueprints.activity.repoUnknown'),
    })
    cursor = index + repositoryId.length
  }
  if (cursor < text.length)
    segments.push({ type: 'text', text: text.slice(cursor) })
  return segments.length ? segments : [{ type: 'text', text }]
}

/**
 * 消息渲染视图：把 `[rule_id]` 前缀拆成中文标签徽标 + 正文（quick-260806-vqh）。
 *
 * 后端把规则标记写进首条消息正文（`question = f"[{rule_id}] {detail}"`），因为
 * `BlueprintThread` 没有 `rule_id` 字段、跨轮去重要靠它反查 —— ⛔ 那行不能改，
 * 所以汉化落在这里。未知 rule_id 回落原始 id（⛔ 不吞）；`[已修复]` 等中文前缀
 * 匹配不上后端那套 `[A-Za-z0-9_]+` 字符集，天然原样保留。
 */
const renderedMessages = computed(() =>
  visibleMessages.value.map((message) => {
    const { ruleId, text } = parseFindingBody(message.body)
    return {
      ...message,
      ruleId,
      ruleLabel: isKnownFindingRule(ruleId)
        ? t(`knowledge.blueprints.thread.rule.${ruleId}`)
        : ruleId,
      text,
      segments: repoAwareSegments(text),
    }
  }),
)

/**
 * ⚠️ 仓内无共享的相对时间工具，`knowledge.blueprints.*` 也没有相对时间单位文案键，
 * 而 i18n 三处追加点已在 115-02 对本相位关闭 ⇒ 退化为本地化的绝对时间（回报而不自补）。
 *
 * quick-260806-tsb：全量 locale 串（`2026/8/6 13:03:22`）在 320px 侧栏里把徽标行挤换行，
 * 收成紧凑档 —— 当日只出 `HH:mm`，当年出 `M月d日 HH:mm`，跨年出日期；完整时间放 `title`。
 */
function formatTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime()))
    return iso
  const now = new Date()
  const time = date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })
  if (date.toDateString() === now.toDateString())
    return time
  if (date.getFullYear() === now.getFullYear())
    return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`
  return date.toLocaleDateString('zh-CN')
}

/** `title` 用的完整时间（紧凑档丢掉的信息在悬浮里找回）。 */
function formatFullTime(iso: string): string {
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

function onGotoAnchor(domId: string): void {
  emit('goto-anchor', domId)
}
</script>

<template>
  <div
    data-testid="blueprint-thread-card"
    :data-thread-id="thread.thread_id"
    :data-thread-kind="thread.kind"
    :data-thread-status="thread.status"
    :data-anchor-status="thread.anchor_status"
    class="rounded-xl border border-border/60 bg-card p-3 space-y-2.5 transition-[border-color,box-shadow,background-color] duration-150"
    :class="active ? 'border-primary/40 bg-primary/2 ring-2 ring-primary/25' : 'hover:border-border'"
  >
    <!-- 选中区（头部摘要）：可点 / 可聚焦；⛔ 内部不放表单控件与长正文 -->
    <button
      type="button"
      data-testid="blueprint-thread-card-select"
      class="flex w-full items-start justify-between gap-2 rounded-md text-left"
      :class="FOCUS_RING_CLASS"
      :aria-pressed="active"
      @click="onSelect"
    >
      <span class="flex min-w-0 flex-wrap items-center gap-1.5">
        <!-- kind 徽标：分组语境（侧栏）冗余 ⇒ showKind=false 时不渲染 -->
        <Badge v-if="showKind" variant="secondary">
          {{ kindLabel }}
        </Badge>
        <!-- 「未分级」（空 severity）是噪音徽标，不渲染 -->
        <Badge v-if="thread.severity" :variant="severityVariant">
          {{ severityLabel }}
        </Badge>
        <Badge :variant="statusVariant">
          {{ statusLabel }}
        </Badge>
        <!-- ⭐ 到期徽标与状态徽标并列而非替换（到期 ≠ 已处置，见 isExpired 注释） -->
        <Badge v-if="isExpired" variant="muted" data-testid="blueprint-thread-expired-badge">
          <span class="icon-[lucide--bell-off] mr-1" aria-hidden="true" />
          {{ t('knowledge.blueprints.thread.expiredBadge') }}
        </Badge>
      </span>
      <span
        class="shrink-0 pt-0.5 text-[11px] tabular-nums text-muted-foreground/80"
        :title="formatFullTime(thread.created_at)"
      >{{ formatTime(thread.created_at) }}</span>
    </button>

    <!-- 失锚：原文已变更，只能给引用时的快照 -->
    <p v-if="isOrphaned" data-testid="blueprint-thread-orphaned" class="text-xs text-muted-foreground">
      {{ t('knowledge.blueprints.annotation.orphaned') }}
    </p>
    <!-- 越界降级：能定位到块但定位不到片段 -->
    <p v-else-if="degraded" data-testid="blueprint-thread-degraded" class="text-xs text-muted-foreground">
      {{ t('knowledge.blueprints.annotation.degraded') }}
    </p>

    <!-- 引用快照：飞书评论式左色条引文；正文默认两行截断，全文在 title -->
    <div
      v-if="quotedText"
      class="rounded-md border-l-2 border-primary/35 bg-muted/40 py-1.5 pl-2.5 pr-2"
      :title="quotedText"
    >
      <p class="text-[11px] text-muted-foreground/80">
        {{ t('knowledge.blueprints.annotation.quotedSnapshot') }}
      </p>
      <pre class="mt-0.5 line-clamp-2 whitespace-pre-wrap break-words text-xs leading-5 text-foreground/85">{{ quotedText }}</pre>
    </div>

    <!-- 无块锚点时明示卡级 / 段级位置；失锚线程仍只展示原文快照，不提供过期跳转。 -->
    <button
      v-if="showAnchorLocation"
      type="button"
      class="flex w-full items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
      data-testid="blueprint-thread-anchor-location"
      :title="t('knowledge.blueprints.thread.gotoAnchorLocation', { location: anchorLocationLabel })"
      @click="onGotoAnchor(anchorDomId)"
    >
      <span class="icon-[lucide--map-pin] shrink-0" aria-hidden="true" />
      <span class="min-w-0 truncate">
        {{ t('knowledge.blueprints.thread.anchorLocation', { location: anchorLocationLabel }) }}
      </span>
      <span class="icon-[lucide--arrow-up-left] ml-auto shrink-0 opacity-60" aria-hidden="true" />
    </button>

    <!-- ⭐ 问答对视图：已答/已关闭的结构化澄清逐题渲染「题面 + 答案 + 功能点跳转」，
         替代整墙 pre（题面/答案默认截断，一键展开全部）。 -->
    <div v-if="showQaView" class="space-y-2" data-testid="blueprint-thread-qa">
      <ol class="space-y-2">
        <li
          v-for="pair in qaPairs"
          :key="pair.no"
          class="space-y-1.5 rounded-lg border border-border/50 bg-muted/20 px-3 py-2.5"
          data-testid="blueprint-thread-qa-item"
        >
          <p class="text-xs leading-5.5 text-muted-foreground" :class="qaExpanded ? '' : 'line-clamp-2'">
            <span class="font-semibold text-foreground/70">{{ pair.no }}.</span> {{ pair.text }}
          </p>
          <p
            v-if="pair.answer"
            class="border-l-2 border-primary/40 pl-2 text-[13px] leading-6 text-foreground"
            :class="qaExpanded ? '' : 'line-clamp-3'"
          >
            {{ pair.answer }}
          </p>
          <div v-if="pair.fpIds.length" class="flex flex-wrap gap-1">
            <button
              v-for="fp in pair.fpIds"
              :key="fp"
              type="button"
              class="inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-left text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
              data-testid="blueprint-thread-qa-fp-chip"
              :title="fp"
              @click="onGotoAnchor(`fp-${fp}`)"
            >
              <span class="truncate">{{ titleOf(fp) }}</span>
              <span class="icon-[lucide--arrow-up-left] shrink-0 opacity-60" aria-hidden="true" />
            </button>
          </div>
        </li>
      </ol>
      <button
        type="button"
        class="text-[11px] text-muted-foreground transition-colors hover:text-primary"
        data-testid="blueprint-thread-qa-toggle"
        @click="qaExpanded = !qaExpanded"
      >
        {{ qaExpanded ? t('knowledge.blueprints.thread.collapseMessage') : t('knowledge.blueprints.thread.expandMessage') }}
      </button>
    </div>

    <!-- 多轮消息（`author_display` 可能是空串：作者是 AI 或已被删） -->
    <!-- ⭐ 结构化向导/问答对视图时跳过首条 AI 编号题面（D-05），避免重复；长消息默认 6 行截断。 -->
    <ul v-if="renderedMessages.length > 0" class="space-y-2.5">
      <li
        v-for="message in renderedMessages"
        :key="message.id"
        data-testid="blueprint-thread-message"
        class="space-y-1"
      >
        <div class="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <Badge :variant="message.author_type === 'ai' ? 'info' : 'secondary'">
            {{ authorLabel(message.author_type, message.author_display) }}
          </Badge>
          <span class="text-[11px] tabular-nums text-muted-foreground/70" :title="formatFullTime(message.created_at)">
            {{ formatTime(message.created_at) }}
          </span>
          <Badge
            v-if="message.ruleLabel"
            variant="outline"
            class="font-normal"
            data-testid="blueprint-thread-message-rule"
            :title="message.ruleId"
          >
            {{ message.ruleLabel }}
          </Badge>
        </div>
        <div
          class="whitespace-pre-wrap break-words text-[13px] leading-6 text-foreground/90"
          :class="isMessageClamped(message.id, message.text) ? 'line-clamp-6' : ''"
        >
          <template v-for="(segment, index) in message.segments" :key="`${message.id}-${index}`">
            <RouterLink
              v-if="segment.type === 'repository' && segment.repositoryId"
              :to="`/repositories/${segment.repositoryId}`"
              class="mx-0.5 inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[11px] text-primary transition-colors hover:border-primary/50 hover:bg-primary/5"
              data-testid="blueprint-thread-repo-link"
            >
              <span class="icon-[lucide--folder-git-2] shrink-0" aria-hidden="true" />
              {{ t('knowledge.blueprints.activity.repoTag', { name: segment.text }) }}
            </RouterLink>
            <template v-else>
              {{ segment.text }}
            </template>
          </template>
        </div>
        <button
          v-if="isMessageExpandable(message.text)"
          type="button"
          class="text-[11px] text-muted-foreground transition-colors hover:text-primary"
          data-testid="blueprint-thread-message-toggle"
          @click="toggleMessage(message.id)"
        >
          {{ expandedMessageIds.has(message.id) ? t('knowledge.blueprints.thread.collapseMessage') : t('knowledge.blueprints.thread.expandMessage') }}
        </button>
      </li>
    </ul>

    <!-- 等待态一行（WAIT-03）：等了多久 · 催过几次 · 上次何时 -->
    <p
      v-if="waitingDays > 0 || thread.last_reminded_at"
      class="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground"
      data-testid="blueprint-thread-waiting"
    >
      <span v-if="waitingDays > 0">{{ t('knowledge.blueprints.thread.waitingSince', { days: waitingDays }) }}</span>
      <span v-if="waitingDays > 0 && thread.last_reminded_at" aria-hidden="true">·</span>
      <span v-if="thread.last_reminded_at">
        {{ reminderCount > 0
          ? t('knowledge.blueprints.thread.remindedWithCount', { n: reminderCount, time: formatTime(thread.last_reminded_at) })
          : t('knowledge.blueprints.thread.reminded', { time: formatTime(thread.last_reminded_at) }) }}
      </span>
    </p>

    <!-- ⭐ 到期说明：明确「不再提醒 ≠ 已解决」，并告知仍可回复 -->
    <p
      v-if="isExpired"
      class="rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-muted-foreground"
      data-testid="blueprint-thread-expired-hint"
    >
      {{ t('knowledge.blueprints.thread.expiredHint', { n: reminderCount }) }}
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
      <!-- ⭐ 确认门指路卡：权威交互面在正文顶部的确认门面板，这里只指路（见 showGateLink 注释） -->
      <div
        v-if="showGateLink"
        class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/25 bg-primary/5 px-2.5 py-2"
      >
        <p class="min-w-0 flex-1 text-xs leading-5 text-muted-foreground">
          {{ t('knowledge.blueprints.thread.gateInlineHint') }}
        </p>
        <Button
          size="sm"
          variant="outline"
          class="shrink-0 text-primary"
          data-testid="blueprint-thread-goto-gate"
          @click="onGotoGate"
        >
          {{ t('knowledge.blueprints.thread.gotoGate') }}
          <span class="icon-[lucide--arrow-up-left] ml-1" aria-hidden="true" />
        </Button>
      </div>
      <!-- 已有可解析的作答（问答对视图在渲染）时向导让位，避免题面双份 -->
      <BlueprintClarificationWizard
        v-else-if="!readonly && !isClosed && useClarificationWizard && !showQaView"
        :questions="structuredQuestions"
        :feature-point-titles="featurePointTitles"
        :submitting="submitting"
        @submit="onAnswer"
        @goto-anchor="onGotoAnchor"
      />
      <BlueprintThreadComposer
        v-else-if="!readonly && !isClosed"
        :options="flatOptions"
        :submitting="submitting"
        @submit="onAnswer"
      />
    </div>
  </div>
</template>
