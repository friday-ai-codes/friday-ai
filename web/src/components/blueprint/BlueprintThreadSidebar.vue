<script setup lang="ts">
/**
 * 线程侧栏（Phase 115-04，UI-SPEC §7.7 / §7.9 / §18.1）。
 *
 * ⭐ **四组判据不在本组件里** —— 一律调 115-02 的纯函数 `sidebarGroups(threads, orphanedThreads)`
 * （`~/utils/blueprintAnnotations`）。理由：前三组除了看 `status`，还必须带上「排除失锚」的
 * 否定项；失锚是**锚定维度**、`status` 是**处置维度**，两者正交。漏掉那个否定项会让一条未决
 * 的失锚线程在侧栏出现两次、计数重复、选中时两处同时高亮（§20 断言 11）。判据只此一份实现，
 * ⛔ 组件内不自写。
 *
 * ⭐ **两个数据源，`threads/` 为准**（§7.7）：前三组来自 §3.4 的 `threads/`（带多轮消息与
 * `options`），第四组来自人审快照的 `orphaned_threads`。同一 `thread_id` 在两处都出现时以
 * `threads/` 的字段为准（它更全），仅在 `threads/` 尚未就绪时用快照条目占位渲染。
 *
 * ⭐ **失锚组直接渲染，⛔ 前端不再按锚点二次过滤**（114-REVIEW MJ-02）：后端的
 * `_has_anchor_locator` 已前置，快照里只有真失锚；前端再按 `anchor.block_id` 滤一遍，
 * 只会把真失锚也滤掉（§20 断言 5 专门逮这个）。
 *
 * ⚠️ 顶部工具条的 `kind` 多选筛选是**用户显式动作**，对四组一视同仁地生效（含失锚组）——
 * 它与上面那条禁令不是一回事：禁的是按**锚点字段**做隐式过滤。
 *
 * a11y（§18.1）：根 `role="complementary"` + `aria-label`；分组用 `ui/collapsible`
 * （`aria-expanded` 由 reka-ui 提供）；线程卡的选中区是 `<button>`，`↑`/`↓` 在**同组内**
 * 移动焦点，`Esc` 清 `activeThreadId`（⛔ 不关闭侧栏）。
 */

import type { BlueprintThreadDetail, BlueprintThreadKind } from '~/types/blueprint'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import { sidebarGroups } from '~/utils/blueprintAnnotations'
import BlueprintThreadCard from './BlueprintThreadCard.vue'

/**
 * 选区草稿的最小形状。
 *
 * ⚠️ 刻意**不 import** 115-03 的 `SelectionPayload`（同波次文件所有权隔离）：本接口是它的
 * 结构子集，115-06 可以把 `SelectionPayload` 直接传进来而无需转换。
 */
export interface BlueprintCommentDraft {
  blockId: string
  startOffset: number
  endOffset: number
  quotedText: string
}

const props = withDefaults(defineProps<{
  /** `threads/` 端点返回的全部线程（带多轮消息与 `options`）。 */
  threads?: BlueprintThreadDetail[]
  /** ⭐ 人审快照的 `orphaned_threads`，直接透传给 `sidebarGroups`。 */
  orphanedThreads?: BlueprintThreadDetail[]
  activeThreadId?: string | null
  /** 可编辑闸；为 `true` 时作答框与草稿卡都不存在于 DOM（§7.9）。 */
  readonly?: boolean
  /** 「显示已关闭批注」开关；关闭时不渲染「已关闭」组。 */
  showClosed?: boolean
  /** `kind` 多选筛选；**空数组 = 不筛选**（⛔ 不用 `null` 表达全选，避免两种空态）。 */
  kindFilters?: string[]
  /** 越界降级线程 id 集合（判据需要块正文 ⇒ 由持有正文的父层算好传入）。 */
  degradedThreadIds?: string[]
  /** 确认门面板是否存在；缺席时线程卡不渲染「前往确认门」链接。 */
  gateAvailable?: boolean
  submitting?: boolean
  /** 选区草稿：非空时侧栏顶部插入一张草稿卡。 */
  draft?: BlueprintCommentDraft | null
}>(), {
  threads: () => [],
  orphanedThreads: () => [],
  activeThreadId: null,
  readonly: false,
  showClosed: false,
  kindFilters: () => [],
  degradedThreadIds: () => [],
  gateAvailable: false,
  submitting: false,
  draft: null,
})

const emit = defineEmits<{
  'select': [threadId: string | null]
  'answer': [threadId: string, body: string]
  'resolve': [threadId: string, reason: string]
  'dismiss': [threadId: string, reason: string]
  'goto-gate': [threadId: string]
  'create-comment': [body: string, draft: BlueprintCommentDraft | null]
  'cancel-comment': []
  'update:kindFilters': [kinds: string[]]
  'update:showClosed': [value: boolean]
}>()

const { t } = useI18n()

/** 四类 `kind` 的筛选 chips（顺序即 §7.7 的「AI 提问 / AI 审查 / 人工评论 / 确认门」）。 */
const KIND_CHIPS: ReadonlyArray<{ kind: BlueprintThreadKind, labelKey: string }> = [
  { kind: 'ai_clarification', labelKey: 'kindAiClarification' },
  { kind: 'ai_review_finding', labelKey: 'kindAiReviewFinding' },
  { kind: 'human_comment', labelKey: 'kindHumanComment' },
  { kind: 'repo_confirmation', labelKey: 'kindRepoConfirmation' },
]

const draftBody = ref('')

/** 空数组 = 全选。 */
function matchesKindFilter(thread: BlueprintThreadDetail): boolean {
  return props.kindFilters.length === 0 || props.kindFilters.includes(thread.kind)
}

function applyKindFilter(list: readonly BlueprintThreadDetail[]): BlueprintThreadDetail[] {
  return (Array.isArray(list) ? list : []).filter(matchesKindFilter)
}

/**
 * ⭐ 两数据源合并：同一 `thread_id` 以 `threads/` 的条目为准（它带多轮消息与 `options`），
 * 快照条目只在 `threads/` 里查不到时占位。⛔ 这里不做任何锚点维度的过滤。
 */
const mergedOrphaned = computed<BlueprintThreadDetail[]>(() => {
  const byId = new Map<string, BlueprintThreadDetail>()
  for (const thread of props.threads)
    byId.set(thread.thread_id, thread)
  return props.orphanedThreads.map(snapshot => byId.get(snapshot.thread_id) ?? snapshot)
})

const visibleThreads = computed(() => applyKindFilter(props.threads))
const visibleOrphaned = computed(() => applyKindFilter(mergedOrphaned.value))

/** ⭐ 四组判据的唯一实现在 115-02 的纯函数里。 */
const groups = computed(() => sidebarGroups(visibleThreads.value, visibleOrphaned.value))

const degradedSet = computed(() => new Set(props.degradedThreadIds))

interface SidebarSection {
  key: 'open' | 'answered' | 'closed' | 'orphaned'
  labelKey: string
  defaultOpen: boolean
  /** ⭐ 失锚组的身份标记做成字段，模板里⛔ 不写锚定态字面量比较（判据只归 `sidebarGroups`）。 */
  isOrphanGroup: boolean
  isClosedGroup: boolean
  items: BlueprintThreadDetail[]
}

const sections = computed<SidebarSection[]>(() => {
  const value = groups.value
  const all: SidebarSection[] = [
    { key: 'open', labelKey: 'groupOpen', defaultOpen: true, isOrphanGroup: false, isClosedGroup: false, items: value.open },
    { key: 'answered', labelKey: 'groupAnswered', defaultOpen: true, isOrphanGroup: false, isClosedGroup: false, items: value.answered },
    { key: 'closed', labelKey: 'groupClosed', defaultOpen: false, isOrphanGroup: false, isClosedGroup: true, items: value.closed },
    { key: 'orphaned', labelKey: 'groupOrphaned', defaultOpen: false, isOrphanGroup: true, isClosedGroup: false, items: value.orphaned },
  ]
  return props.showClosed ? all : all.filter(section => !section.isClosedGroup)
})

const totalCount = computed(() =>
  sections.value.reduce((sum, section) => sum + section.items.length, 0),
)

const isEmpty = computed(() => totalCount.value === 0)

const canDraft = computed(() => props.draft !== null && !props.readonly)
const isDraftEmpty = computed(() => draftBody.value.trim().length === 0)

function toggleKind(kind: string): void {
  const next = props.kindFilters.includes(kind)
    ? props.kindFilters.filter(item => item !== kind)
    : [...props.kindFilters, kind]
  emit('update:kindFilters', next)
}

function submitDraft(): void {
  if (isDraftEmpty.value || props.submitting)
    return
  emit('create-comment', draftBody.value.trim(), props.draft)
  draftBody.value = ''
}

function cancelDraft(): void {
  draftBody.value = ''
  emit('cancel-comment')
}

/**
 * `↑`/`↓` 只在**同组内**移动焦点；`Esc` 清选中态但**不关闭侧栏**（§18.1）。
 * ⚠️ 焦点在草稿卡内时 `Esc` 改为放弃草稿 —— 与草稿卡上的「取消」按钮等效，
 * 因为 `knowledge.blueprints.thread.*` 缺该文案键，而 i18n 追加点已由 115-02 对本相位
 * 关闭（§13.2：回报而不自补，缺口已登记在 115-04-SUMMARY）。
 */
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    const inDraft = (event.target as HTMLElement | null)?.closest?.('[data-testid="blueprint-thread-draft"]')
    if (inDraft) {
      cancelDraft()
      return
    }
    emit('select', null)
    return
  }
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')
    return
  const current = event.target as HTMLElement | null
  const group = current?.closest?.('[data-group-key]')
  if (!group)
    return
  const cards = Array.from(
    group.querySelectorAll<HTMLElement>('[data-testid="blueprint-thread-card-select"]'),
  )
  const index = cards.findIndex(card => card === current || card.contains(current))
  if (index < 0)
    return
  const next = event.key === 'ArrowDown' ? index + 1 : index - 1
  if (next < 0 || next >= cards.length)
    return
  event.preventDefault()
  cards[next].focus()
}
</script>

<template>
  <aside
    data-testid="blueprint-thread-sidebar"
    role="complementary"
    :aria-label="t('knowledge.blueprints.annotation.sidebarToggleAria', { n: totalCount })"
    class="flex h-full flex-col gap-3"
    @keydown="onKeydown"
  >
    <!-- 顶部工具条：kind 多选 chips + 显示已关闭批注 -->
    <div class="space-y-2">
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="chip in KIND_CHIPS"
          :key="chip.kind"
          type="button"
          data-testid="blueprint-kind-chip"
          :data-kind="chip.kind"
          :aria-pressed="kindFilters.includes(chip.kind)"
          class="rounded-full border px-2.5 py-1 text-xs transition-colors"
          :class="kindFilters.includes(chip.kind)
            ? 'border-primary bg-primary/10 text-primary'
            : 'border-border/60 text-muted-foreground hover:bg-muted'"
          @click="toggleKind(chip.kind)"
        >
          {{ t(`knowledge.blueprints.thread.${chip.labelKey}`) }}
        </button>
      </div>

      <!-- ⭐ `<label>` 而不是 `<div>`：`Switch` 上既无 `aria-label` 也无 `id`/`for`，包一层
           label 才能同时拿到可访问名与「点文字也切换」。写法照顶栏那个同名开关。 -->
      <label class="flex items-center gap-2">
        <Switch
          data-testid="blueprint-show-closed"
          :model-value="showClosed"
          @update:model-value="emit('update:showClosed', $event)"
        />
        <span class="text-xs text-foreground">{{ t('knowledge.blueprints.annotation.showClosed') }}</span>
      </label>
      <p class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.annotation.showClosedHint') }}
      </p>
    </div>

    <!-- 选区草稿卡：readonly 时不渲染 -->
    <div
      v-if="canDraft"
      data-testid="blueprint-thread-draft"
      class="space-y-2 rounded-xl border border-primary/40 bg-primary/5 p-3"
    >
      <p class="text-xs font-medium text-foreground">
        {{ t('knowledge.blueprints.thread.draftTitle') }}
      </p>
      <pre class="whitespace-pre-wrap break-words rounded-lg bg-muted/50 px-2.5 py-1.5 font-mono text-xs leading-5">{{ draft?.quotedText }}</pre>
      <Textarea
        v-model="draftBody"
        data-testid="blueprint-thread-draft-input"
        class="min-h-20 text-sm"
        :placeholder="t('knowledge.blueprints.thread.composerPlaceholder')"
      />
      <div class="flex items-center justify-end gap-2">
        <Button
          size="sm"
          variant="ghost"
          data-testid="blueprint-thread-draft-cancel"
          @click="cancelDraft"
        >
          {{ t('knowledge.blueprints.thread.draftCancel') }}
        </Button>
        <Button
          size="sm"
          data-testid="blueprint-thread-draft-submit"
          :disabled="isDraftEmpty || submitting"
          @click="submitDraft"
        >
          {{ t('knowledge.blueprints.thread.draftSubmit') }}
        </Button>
      </div>
    </div>

    <!-- 空态：四组皆空 -->
    <CompactEmptyState
      v-if="isEmpty"
      data-testid="blueprint-thread-empty"
      icon="lucide--messages-square"
      :title="t('knowledge.blueprints.annotation.emptyTitle')"
      :description="t('knowledge.blueprints.annotation.emptyBody')"
    />

    <div v-else class="space-y-2 overflow-y-auto">
      <Collapsible
        v-for="section in sections"
        :key="section.key"
        :data-group-key="section.key"
        :data-testid="`blueprint-thread-group-${section.key}`"
        :default-open="section.defaultOpen"
      >
        <CollapsibleTrigger class="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left text-sm font-medium hover:bg-muted/60">
          <span class="text-foreground">{{ t(`knowledge.blueprints.thread.${section.labelKey}`) }}</span>
          <Badge :variant="section.isOrphanGroup && section.items.length > 0 ? 'warning' : 'muted'">
            {{ section.items.length }}
          </Badge>
        </CollapsibleTrigger>
        <CollapsibleContent class="space-y-2 pt-1.5">
          <p
            v-if="section.isOrphanGroup && section.items.length === 0"
            class="px-1 text-xs text-muted-foreground"
          >
            {{ t('knowledge.blueprints.thread.groupOrphanedEmpty') }}
          </p>
          <BlueprintThreadCard
            v-for="thread in section.items"
            :key="thread.thread_id"
            :thread="thread"
            :active="thread.thread_id === activeThreadId"
            :readonly="readonly"
            :submitting="submitting"
            :degraded="degradedSet.has(thread.thread_id)"
            :gate-available="gateAvailable"
            @select="emit('select', $event)"
            @answer="(id, body) => emit('answer', id, body)"
            @resolve="(id, reason) => emit('resolve', id, reason)"
            @dismiss="(id, reason) => emit('dismiss', id, reason)"
            @goto-gate="emit('goto-gate', $event)"
          />
        </CollapsibleContent>
      </Collapsible>
    </div>
  </aside>
</template>
