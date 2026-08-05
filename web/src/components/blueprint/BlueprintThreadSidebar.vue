<script setup lang="ts">
/**
 * 线程侧栏（Phase 115-04，UI-SPEC §7.7 / §7.9 / §18.1；quick-260806-2c2 改为按 kind 分组）。
 *
 * ⭐ **分组判据不在本组件里** —— 一律调纯函数 `sidebarKindGroups(threads, orphanedThreads)`
 * （`~/utils/blueprintAnnotations`）：按 `kind` 分四组（AI 提问 / AI 审查 / 人工评论 / 确认门），
 * 组内 `open` → `answered` → closed，再按 severity → `created_at`。判据只此一份实现，
 * ⛔ 组件内不自写。分组本身取代了此前的 kind 筛选 chips（已删）；「显示已关闭批注」开关
 * 只保留顶栏一处（BlueprintViewerHeader），侧栏不再重复渲染。
 *
 * ⭐ **两个数据源，`threads/` 为准**（§7.7）：`threads/` 带多轮消息与 `options`，人审快照的
 * `orphaned_threads` 只在 `threads/` 尚未就绪时占位渲染。同一 `thread_id` 在两处都出现时以
 * `threads/` 的字段为准（它更全）。
 *
 * ⭐ **失锚线程并入各自 kind 组**，不再有专属失锚组与其空态：失锚是锚定维度，卡片上的
 * 失锚标记由 `BlueprintThreadCard` 承载。快照的 `orphaned_threads` 仍直接渲染，⛔ 前端不按
 * 锚点二次过滤（114-REVIEW MJ-02：后端 `_has_anchor_locator` 已前置，快照里只有真失锚）。
 *
 * a11y（§18.1）：根 `role="complementary"` + `aria-label`。⚠️ landmark 的名字必须是**名词
 * 短语**（读屏按 landmark 列表导航时念的就是它），⛔ 不能用「查看批注，共 N 条」这种**动作
 * 描述**兼计数 —— 计数已由各分组 Badge 提供，塞进 landmark 名只会让每次导航都被读一长串。
 * 分组用 `ui/collapsible`
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
import { Textarea } from '~/components/ui/textarea'
import { sidebarKindGroups } from '~/utils/blueprintAnnotations'
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
  /** 「显示已关闭批注」开关；关闭时各 kind 组内不渲染 closed 条目。 */
  showClosed?: boolean
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
  'update:showClosed': [value: boolean]
}>()

const { t } = useI18n()

const draftBody = ref('')

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

/** ⭐ 分组判据的唯一实现在纯函数 `sidebarKindGroups` 里（含去重与组内排序）。 */
const groups = computed(() => sidebarKindGroups(props.threads, mergedOrphaned.value))

const degradedSet = computed(() => new Set(props.degradedThreadIds))

interface SidebarSection {
  key: BlueprintThreadKind
  labelKey: string
  items: BlueprintThreadDetail[]
}

/** 四组固定顺序（§7.7 的「AI 提问 / AI 审查 / 人工评论 / 确认门」），i18n 前缀 `knowledge.blueprints.thread.`。 */
const SECTION_DEFS: ReadonlyArray<{ key: BlueprintThreadKind, labelKey: string }> = [
  { key: 'ai_clarification', labelKey: 'kindAiClarification' },
  { key: 'ai_review_finding', labelKey: 'kindAiReviewFinding' },
  { key: 'human_comment', labelKey: 'kindHumanComment' },
  { key: 'repo_confirmation', labelKey: 'kindRepoConfirmation' },
]

function isClosedThread(thread: BlueprintThreadDetail): boolean {
  return thread.status === 'resolved' || thread.status === 'dismissed'
}

const sections = computed<SidebarSection[]>(() => {
  return SECTION_DEFS
    .map(def => ({
      key: def.key,
      labelKey: def.labelKey,
      // ⭐ closed 的显隐是本组件「显示已关闭批注」开关的职责，⛔ 不进纯函数：
      // hiddenClosedCount 还要靠同一份未过滤产物计数，进了纯函数就得跑两遍分组。
      items: props.showClosed
        ? groups.value[def.key]
        : groups.value[def.key].filter(thread => !isClosedThread(thread)),
    }))
    // ⭐ 空组整块（含标题行）不渲染 —— 分组本身取代筛选，一排空组是纯噪音。
    // 失锚组恒在的旧例外已随失锚组一并废弃（失锚线程并入各自 kind 组）。
    .filter(section => section.items.length > 0)
})

const totalCount = computed(() =>
  sections.value.reduce((sum, section) => sum + section.items.length, 0),
)

const isEmpty = computed(() => totalCount.value === 0)

/**
 * ⭐ 空态但存在被隐藏的已关闭批注（115 评审 P1 的另一半）：顶栏「批注 {n}」按全量
 * 计数（含已关闭），而侧栏默认滤掉 closed 条目 —— 不交代这 n 条去了哪，就是「批注 1 →
 * 点开 → 空的」的自相矛盾。此时空态必须说明有几条被隐藏并给一键开关。
 * 口径：合并去重后的全量线程（`sidebarKindGroups` 的未过滤产物）里数 closed。
 */
const hiddenClosedCount = computed(() => {
  if (props.showClosed)
    return 0
  return SECTION_DEFS.reduce(
    (sum, def) => sum + groups.value[def.key].filter(isClosedThread).length,
    0,
  )
})

const canDraft = computed(() => props.draft !== null && !props.readonly)
const isDraftEmpty = computed(() => draftBody.value.trim().length === 0)

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
    :aria-label="t('knowledge.blueprints.annotation.sidebarTitle')"
    class="flex h-full flex-col gap-3"
    @keydown="onKeydown"
  >
    <!-- ⛔ 侧栏内不再放「显示已关闭批注」开关 —— 顶栏工具条已有同名开关（BlueprintViewerHeader），
         两处并存会出现两个联动的 Switch（用户实测点名的重复）。`showClosed` 状态仍由父层传入，
         空态里的一键「显示」按钮保留（那是上下文动作，不是常驻开关）。
         点线图例提示只在开关打开时展示（渐进披露）。 -->
    <p v-if="showClosed" class="border-b border-border/50 pb-3 text-xs text-muted-foreground">
      {{ t('knowledge.blueprints.annotation.showClosedHint') }}
    </p>

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

    <!-- 空态（有隐藏的已关闭批注）：交代去向 + 一键显示，⛔ 不与「真的空」同形 -->
    <div
      v-if="isEmpty && hiddenClosedCount > 0"
      class="flex flex-col items-center gap-1.5 rounded-xl border border-dashed border-border/70 bg-muted/10 px-4 py-6 text-center"
      data-testid="blueprint-thread-empty-closed"
    >
      <span class="mb-0.5 flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/10">
        <span class="icon-[lucide--check] text-base text-emerald-600" aria-hidden="true" />
      </span>
      <p class="text-sm font-medium text-foreground">
        {{ t('knowledge.blueprints.annotation.emptyClosedTitle') }}
      </p>
      <p class="text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.annotation.emptyClosedBody', { n: hiddenClosedCount }) }}
      </p>
      <Button
        size="sm"
        variant="ghost"
        class="mt-1 text-primary"
        data-testid="blueprint-thread-show-closed-action"
        @click="emit('update:showClosed', true)"
      >
        {{ t('knowledge.blueprints.annotation.emptyClosedAction') }}
      </Button>
    </div>

    <!-- 空态：四组皆空且无隐藏项 -->
    <CompactEmptyState
      v-else-if="isEmpty"
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
        :default-open="true"
      >
        <!-- `min-h-11` = §2 的 44px 例外（本行逐字点名「线程侧栏的折叠箭头」）：
             窄屏抽屉里这是实际触控目标，`py-1.5` 只有 ~30px 高。 -->
        <CollapsibleTrigger
          data-testid="blueprint-thread-group-trigger"
          class="group flex min-h-11 w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left text-sm font-medium hover:bg-muted/60"
        >
          <span class="text-foreground">
            {{ t(`knowledge.blueprints.thread.${section.labelKey}`) }}
          </span>
          <!-- ⭐ 0 不出徽标（灰色的 0 会被读成「有一项待办」，与顶栏计数同一条纪律）；
               空组本就不渲染 ⇒ 恒显示，variant 统一 muted -->
          <Badge v-if="section.items.length > 0" variant="muted">
            {{ section.items.length }}
          </Badge>
          <span
            class="icon-[lucide--chevron-down] ml-auto shrink-0 text-muted-foreground/70 transition-transform group-data-[state=closed]:-rotate-90"
            aria-hidden="true"
          />
        </CollapsibleTrigger>
        <CollapsibleContent class="space-y-2 pt-1.5">
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
