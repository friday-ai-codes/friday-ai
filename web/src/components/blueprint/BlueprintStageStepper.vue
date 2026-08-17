<script setup lang="ts">
/**
 * 横向节点进度 stepper（quick-260806 节点重跑，替换原「阶段时间线 + 阶段全景」两块纵向面板）。
 *
 * 一排八个流程节点（顺序 = `BLUEPRINT_STAGES`），节点间连接线表示流向；点击任一节点在下方
 * 展开该节点的详情区（单选，可用上一步/下一步切换）：摘要事实与耗时、该节点的全部事件明细、
 * 该节点的 `stage_state` 分片（来自 stages API）、带指令重跑表单与重跑历史。
 *
 * ## 四条纪律
 *
 * 1. ⭐ **状态推断与事件归属全部委托 `buildStagePanorama` → `buildStageTimeline`**：那是全相位
 *    唯一的一份实现（位序收敛 / 终态折叠 / 每仓事件计数判据都在里面）。⛔ 本组件不写第三份。
 * 2. ⭐ **UI 节点 key ≠ 后端 stage key**：时间线侧叫 `confirmation`，后端叫 `repo_confirmation`；
 *    `pending_review` 是前端虚拟节点，后端根本没有。重跑请求与 `stage_state` 取片都必须先过
 *    `UI_TO_BACKEND_STAGE` 映射，⛔ 不要「统一命名」（两侧各有既有消费方）。
 * 3. ⭐ **`stage_state` 分片是零 schema 保证的裸 JSON**：走 `describeEventPayload` 折成
 *    「标量字段 + 展开的复合键 + 折叠的原始 JSON」，⛔ 不整页倾倒大 JSON。
 * 4. ⛔ **本组件只 emit 不发请求**（与顶栏同款纪律）：重跑 POST、toast 与查询失效都归页面。
 */

import type { BlueprintEvent, BlueprintStageRerunMarker, BlueprintStagesResponse } from '~/types/blueprint'
import type { PanoramaEventRow, StagePanoramaNode } from '~/utils/blueprintActivity'
import type { StageState } from '~/utils/blueprintBlocks'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  buildStagePanorama,
  describeEventPayload,
  humanizeEnumToken,
  humanizePayloadEnums,
} from '~/utils/blueprintActivity'
import { resolveProgressKeys } from '~/utils/blueprintBlocks'

const props = withDefaults(defineProps<{
  events?: BlueprintEvent[]
  /** `blueprint/events/` 的 `current_stage`（阶段状态推断要它）。 */
  currentStage?: string
  /** 人审快照的 `current_status`（⛔ 前端不自行推断状态）。 */
  currentStatus?: string
  /** stages API 的节点快照；查询未落地 / 失败时为 `null`（重跑面与状态分片降级不渲染）。 */
  stages?: BlueprintStagesResponse | null
  /** 重跑请求在途（页面持有 mutation 状态，本组件只用来锁按钮）。 */
  submitting?: boolean
}>(), {
  events: () => [],
  currentStage: '',
  currentStatus: '',
  stages: null,
  submitting: false,
})

const emit = defineEmits<{
  /** 带指令重跑；`stage` 已映射成**后端 stage key**。 */
  'rerun': [payload: { stage: string, instruction: string }]
  /** 打开按仓调研明细抽屉（结论 + agent 过程日志）。 */
  'view-research': []
}>()

const { t, te } = useI18n()

/**
 * UI 八节点 key → 后端 stage key。`pending_review` 是前端虚拟节点 ⇒ 空串（无状态分片、
 * 不可重跑）。`intake` / `decompose` 两个准备 stage 不在时间线上（与 `buildStageTimeline`
 * 的 `PRE_TIMELINE_SESSION_STAGES` 同口径），它们的状态分片刻意不折进任何节点。
 */
const UI_TO_BACKEND_STAGE: Record<string, string> = {
  route: 'route',
  repo_research: 'repo_research',
  confirmation: 'repo_confirmation',
  spec_gate: 'spec_gate',
  repo_plan: 'repo_plan',
  merge: 'merge',
  ai_review: 'ai_review',
  pending_review: '',
}

const nodes = computed<StagePanoramaNode[]>(() =>
  buildStagePanorama(props.events, props.currentStage, props.currentStatus),
)

// ── 选中态（单选；默认自动落在进行中 / 失败节点上）────────────────────────────

/** `null` = 未手动操作过（跟随自动落点）；`''` = 用户主动收起。 */
const manualStage = ref<string | null>(null)

const autoStage = computed(() => {
  const focus = nodes.value.find(node => node.state === 'failed')
    ?? nodes.value.find(node => node.state === 'running')
  return focus?.stage ?? ''
})

const activeStage = computed(() => (manualStage.value === null ? autoStage.value : manualStage.value))

const activeNode = computed(() =>
  nodes.value.find(node => node.stage === activeStage.value) ?? null,
)

const activeIndex = computed(() =>
  nodes.value.findIndex(node => node.stage === activeStage.value),
)

/**
 * 只有这两个节点会起容器跑 agent（阶段一按仓调研、阶段二按仓出分仓方案）⇒ 也只有它们
 * 有过程日志可看。其余节点挂入口会把用户送进一个必然为空的抽屉。
 */
const RESEARCH_DETAIL_STAGES = new Set(['repo_research', 'repo_plan'])

const showResearchEntry = computed(() => RESEARCH_DETAIL_STAGES.has(activeStage.value))

function toggleNode(stage: string): void {
  manualStage.value = activeStage.value === stage ? '' : stage
}

function step(delta: number): void {
  const list = nodes.value
  if (!list.length)
    return
  const index = activeIndex.value < 0 ? (delta > 0 ? -1 : list.length) : activeIndex.value
  const next = Math.min(list.length - 1, Math.max(0, index + delta))
  manualStage.value = list[next].stage
}

// ── 状态与文案 ────────────────────────────────────────────────────────────────

const STATE_VARIANT: Record<StageState, 'muted' | 'info' | 'success' | 'destructive'> = {
  idle: 'muted',
  running: 'info',
  done: 'success',
  failed: 'destructive',
}

const STATE_LABEL_KEY: Record<StageState, string> = {
  idle: 'stateIdle',
  running: 'stateRunning',
  done: 'stateDone',
  failed: 'stateFailed',
}

function stageLabel(stage: string): string {
  return t(`knowledge.blueprints.stage.${stage}`)
}

function stateLabel(state: StageState): string {
  return t(`knowledge.blueprints.stage.${STATE_LABEL_KEY[state]}`)
}

/** 等澄清标识：进行中节点若正卡在人工澄清上，用醒目的问号态替换脉冲点。 */
const waitingClarification = computed(
  () => props.currentStatus === 'needs_clarification'
    || props.stages?.session_status === 'waiting_clarification',
)

function nodeIsWaiting(node: StagePanoramaNode): boolean {
  return node.state === 'running' && waitingClarification.value
}

/** 摘要事实标签：`activity.fact.*`；未配文案回落键名本身（与旧全景同口径）。 */
function factLabel(key: string): string {
  const full = `knowledge.blueprints.activity.fact.${key}`
  return te(full) ? t(full) : key
}

/** payload / stage_state 键的可读标签：`activity.payload.*`；未配则原样 mono 显示。 */
function fieldLabel(key: string): string {
  const full = `knowledge.blueprints.activity.payload.${key}`
  return te(full) ? t(full) : key
}

function fieldValue(value: string): string {
  // 置信度 / 适配结论走 i18n 键；true/false 沿用 activity.yes/no；其余原样
  if (value === 'high')
    return t('knowledge.blueprints.activity.confidenceHigh')
  if (value === 'medium')
    return t('knowledge.blueprints.activity.confidenceMedium')
  if (value === 'low')
    return t('knowledge.blueprints.activity.confidenceLow')
  if (value === 'suitable')
    return t('knowledge.blueprints.repo.fitnessSuitable')
  if (value === 'partial')
    return t('knowledge.blueprints.repo.fitnessPartial')
  if (value === 'unsuitable')
    return t('knowledge.blueprints.repo.fitnessUnsuitable')
  if (value === 'true')
    return t('knowledge.blueprints.activity.yes')
  if (value === 'false')
    return t('knowledge.blueprints.activity.no')
  // 兜底：与 humanizeEnumToken 对齐，避免漏映射时标题/字段露出英文
  const fallback = humanizeEnumToken(value)
  return fallback
}

/** 事件中文名：取键与兜底一律走 `resolveProgressKeys`（与旧时间线/全景逐字同口径）。 */
function eventLabel(row: PanoramaEventRow): string {
  const { key, fallbackKey } = resolveProgressKeys(row.event, row.payload)
  if (!key)
    return row.event
  // 插值前浅拷贝人话化，避免标题里出现 suitable/high 英文
  const displayPayload = humanizePayloadEnums(row.payload)
  if (te(key))
    return t(key, displayPayload)
  return te(fallbackKey) ? t(fallbackKey) : row.event
}

function formatTime(raw: string): string {
  if (!raw)
    return ''
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleString('zh-CN', { hour12: false })
}

/** 耗时：秒以下给毫秒，分钟以下给秒，其余给「Xm Ys」（与旧全景同款）。 */
function formatDuration(ms: number | null): string {
  if (ms === null || ms <= 0)
    return ''
  if (ms < 1000)
    return `${ms}ms`
  if (ms < 60_000)
    return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes}m ${seconds}s`
}

// ── stage_state 分片（来自 stages API）────────────────────────────────────────

const stageStateByKey = computed<Map<string, Record<string, unknown>>>(() => {
  const map = new Map<string, Record<string, unknown>>()
  for (const entry of props.stages?.stages ?? []) {
    if (entry && typeof entry.state === 'object' && entry.state !== null)
      map.set(String(entry.key), entry.state)
  }
  return map
})

/** 选中节点的 stage_state 分片，折成「标量 + 复合键展开 + 原始 JSON」三层可读结构。 */
const activeStageState = computed(() => {
  const backendKey = UI_TO_BACKEND_STAGE[activeStage.value] ?? ''
  if (!backendKey)
    return null
  const slice = stageStateByKey.value.get(backendKey)
  if (!slice || Object.keys(slice).length === 0)
    return null
  return describeEventPayload(slice)
})

/** 原始 JSON 折叠展开集合（stage_state 与事件明细共用同一交互）。 */
const rawOpen = ref<Set<string>>(new Set())
function toggleRaw(id: string): void {
  const next = new Set(rawOpen.value)
  if (next.has(id))
    next.delete(id)
  else next.add(id)
  rawOpen.value = next
}

// ── 带指令重跑 ────────────────────────────────────────────────────────────────

const rerunnableStages = computed<Set<string>>(
  () => new Set(props.stages?.rerunnable_stages ?? []),
)

/** 重跑入口只在「有会话 + 该节点映射到可重跑的后端 stage」时渲染；越界判定归后端。 */
const activeRerunStage = computed(() => {
  if (!props.stages?.session_id)
    return ''
  const backendKey = UI_TO_BACKEND_STAGE[activeStage.value] ?? ''
  return backendKey && rerunnableStages.value.has(backendKey) ? backendKey : ''
})

const instruction = ref('')

function submitRerun(): void {
  if (!activeRerunStage.value || props.submitting)
    return
  emit('rerun', { stage: activeRerunStage.value, instruction: instruction.value.trim() })
}

// ── 整篇重新生成（decompose 重跑 = major 版本递增，如 v1 → v2）────────────────
//
// `decompose` 不在时间线八节点上（PRE_TIMELINE 口径），但它是「需求变更整篇重做」的
// 唯一入口 ⇒ 挂在头部而不是某个节点的详情区。

const canFullRerun = computed(
  () => Boolean(props.stages?.session_id) && rerunnableStages.value.has('decompose'),
)

const fullRerunOpen = ref(false)
const fullInstruction = ref('')

function submitFullRerun(): void {
  if (!canFullRerun.value || props.submitting)
    return
  emit('rerun', { stage: 'decompose', instruction: fullInstruction.value.trim() })
}

/** 选中节点的重跑历史（当前标记 + 历史，按时间倒序；两处形状相同）。 */
const activeRerunHistory = computed<BlueprintStageRerunMarker[]>(() => {
  const backendKey = UI_TO_BACKEND_STAGE[activeStage.value] ?? ''
  if (!backendKey || !props.stages)
    return []
  const rows = [...props.stages.stage_rerun_history]
  const marker = props.stages.stage_rerun
  if (marker && !rows.some(row => row.requested_at === marker.requested_at && row.stage === marker.stage))
    rows.push(marker)
  return rows
    .filter(row => String(row.stage) === backendKey)
    .sort((a, b) => String(b.requested_at).localeCompare(String(a.requested_at)))
})

/** 折叠态单行摘要：失败 > 进行中 > 全部完成（沿用旧时间线口径）。 */
const summary = computed(() => {
  const failed = nodes.value.find(node => node.state === 'failed')
  if (failed)
    return { text: t('knowledge.blueprints.stage.summaryFailed', { label: stageLabel(failed.stage) }), variant: 'destructive' as const }
  const running = nodes.value.find(node => node.state === 'running')
  if (running)
    return { text: t('knowledge.blueprints.stage.summaryCurrent', { label: stageLabel(running.stage) }), variant: 'info' as const }
  if (nodes.value.some(node => node.state === 'done'))
    return { text: t('knowledge.blueprints.stage.summaryDone'), variant: 'success' as const }
  return null
})

const runLabel = computed(() => String(props.stages?.run_label ?? ''))

/** 节点圆圈的语义类（零颜色字面量之外的例外：这里全部走语义 token）。 */
function circleClass(node: StagePanoramaNode): string {
  if (node.state === 'failed')
    return 'border-destructive/60 bg-destructive/10 text-destructive'
  if (node.state === 'done')
    return 'border-success/50 bg-success/10 text-success'
  if (node.state === 'running') {
    return nodeIsWaiting(node)
      ? 'border-warning/60 bg-warning/10 text-warning-emphasis'
      : 'border-info/60 bg-info/10 text-info'
  }
  return 'border-border bg-muted/30 text-muted-foreground'
}

/** 连接线：来向节点已完成 ⇒ 实色，否则弱化。 */
function connectorClass(index: number): string {
  const from = nodes.value[index]
  return from && (from.state === 'done')
    ? 'bg-success/50'
    : 'bg-border'
}
</script>

<template>
  <section class="card" data-testid="blueprint-stage-stepper">
    <!-- 头部：标题 + 轮次 + 单行摘要 -->
    <div class="flex flex-wrap items-center gap-2 px-5 py-3.5">
      <span class="icon-[lucide--git-commit-horizontal] text-primary" aria-hidden="true" />
      <h2 class="text-base font-semibold">
        {{ t('knowledge.blueprints.stepper.title') }}
      </h2>
      <Badge v-if="runLabel" variant="muted" class="tabular-nums" data-testid="blueprint-stepper-run-label">
        {{ t('knowledge.blueprints.stepper.runLabel', { label: runLabel }) }}
      </Badge>
      <Badge v-if="summary" :variant="summary.variant" data-testid="blueprint-stepper-summary">
        {{ summary.text }}
      </Badge>
      <Button
        v-if="canFullRerun"
        variant="ghost"
        size="sm"
        class="ml-auto text-muted-foreground"
        data-testid="blueprint-stepper-full-rerun-toggle"
        :aria-expanded="fullRerunOpen"
        @click="fullRerunOpen = !fullRerunOpen"
      >
        <span class="icon-[lucide--refresh-ccw-dot] mr-1.5" aria-hidden="true" />
        {{ t('knowledge.blueprints.rerun.fullTitle') }}
      </Button>
    </div>

    <!-- 整篇重新生成表单（decompose 重跑 = 新的大版本；历史版本全部保留） -->
    <div
      v-if="canFullRerun && fullRerunOpen"
      class="border-t border-border/50 px-5 py-3.5"
      data-testid="blueprint-stepper-full-rerun-form"
    >
      <p class="mb-2 text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.rerun.fullHint') }}
      </p>
      <textarea
        v-model="fullInstruction"
        rows="2"
        class="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40"
        :placeholder="t('knowledge.blueprints.rerun.fullPlaceholder')"
        data-testid="blueprint-stepper-full-rerun-input"
      />
      <div class="mt-2 flex justify-end">
        <Button
          variant="outline"
          size="sm"
          :disabled="submitting"
          data-testid="blueprint-stepper-full-rerun-submit"
          @click="submitFullRerun()"
        >
          <span
            :class="submitting ? 'icon-[lucide--loader-2] animate-spin' : 'icon-[lucide--refresh-ccw-dot]'"
            class="mr-1.5"
            aria-hidden="true"
          />
          {{ t('knowledge.blueprints.rerun.fullSubmit') }}
        </Button>
      </div>
    </div>

    <!-- ① 横向节点排（窄屏横向滚动） -->
    <div class="overflow-x-auto border-t border-border/50 px-5 py-4">
      <ol class="flex min-w-max items-start">
        <li
          v-for="(node, index) in nodes"
          :key="node.stage"
          class="flex items-start"
          data-testid="blueprint-stepper-node"
          :data-stage="node.stage"
          :data-state="node.state"
          :data-active="node.stage === activeStage ? 'true' : undefined"
        >
          <button
            type="button"
            class="group flex w-20 flex-col items-center gap-1.5 rounded-lg px-1 py-1 text-center transition-colors hover:bg-muted/40"
            :aria-expanded="node.stage === activeStage"
            :aria-label="t('knowledge.blueprints.stepper.nodeAria', { label: stageLabel(node.stage) })"
            data-testid="blueprint-stepper-node-button"
            @click="toggleNode(node.stage)"
          >
            <span
              class="relative flex size-8 shrink-0 items-center justify-center rounded-full border transition-shadow"
              :class="[circleClass(node), node.stage === activeStage ? 'ring-2 ring-primary/50 ring-offset-2 ring-offset-background' : '']"
            >
              <!-- 运行中：脉冲动效；等澄清：醒目问号；完成/失败/未开始各有图标 -->
              <template v-if="node.state === 'running'">
                <span
                  v-if="!nodeIsWaiting(node)"
                  class="absolute inline-flex size-full animate-ping rounded-full bg-info/30"
                  aria-hidden="true"
                />
                <span
                  :class="nodeIsWaiting(node) ? 'icon-[lucide--help-circle]' : 'icon-[lucide--loader-2] animate-spin'"
                  aria-hidden="true"
                />
              </template>
              <span v-else-if="node.state === 'done'" class="icon-[lucide--check]" aria-hidden="true" />
              <span v-else-if="node.state === 'failed'" class="icon-[lucide--x]" aria-hidden="true" />
              <span v-else class="icon-[lucide--circle-dashed] opacity-60" aria-hidden="true" />
            </span>
            <span
              class="w-full truncate text-xs leading-tight"
              :class="node.stage === activeStage ? 'font-medium text-foreground' : 'text-muted-foreground group-hover:text-foreground'"
            >
              {{ stageLabel(node.stage) }}
            </span>
            <span v-if="node.events.length" class="text-[11px] tabular-nums text-muted-foreground/70">
              {{ t('knowledge.blueprints.activity.eventCount', { n: node.events.length }) }}
            </span>
          </button>
          <!-- 连接线（末节点之后不画） -->
          <span
            v-if="index < nodes.length - 1"
            class="mt-4.5 h-0.5 w-8 shrink-0 rounded-full"
            :class="connectorClass(index)"
            aria-hidden="true"
          />
        </li>
      </ol>
    </div>

    <!-- ② 节点详情区（单选展开） -->
    <div
      v-if="activeNode"
      class="border-t border-border/50 p-5"
      data-testid="blueprint-stepper-detail"
      :data-stage="activeNode.stage"
    >
      <!-- 详情头：节点名 + 状态 + 耗时 + 上一步/下一步 -->
      <div class="flex flex-wrap items-center gap-2">
        <Badge variant="muted" class="tabular-nums">
          {{ t('knowledge.blueprints.activity.step', { n: activeNode.index }) }}
        </Badge>
        <h3 class="text-base font-semibold">
          {{ stageLabel(activeNode.stage) }}
        </h3>
        <Badge :variant="STATE_VARIANT[activeNode.state]">
          {{ stateLabel(activeNode.state) }}
        </Badge>
        <span v-if="formatDuration(activeNode.durationMs)" class="text-xs tabular-nums text-muted-foreground">
          {{ t('knowledge.blueprints.stepper.duration', { d: formatDuration(activeNode.durationMs) }) }}
        </span>

        <div class="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            :disabled="activeIndex <= 0"
            data-testid="blueprint-stepper-prev"
            @click="step(-1)"
          >
            <span class="icon-[lucide--chevron-left] mr-1" aria-hidden="true" />
            {{ t('knowledge.blueprints.stepper.prev') }}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :disabled="activeIndex >= nodes.length - 1"
            data-testid="blueprint-stepper-next"
            @click="step(1)"
          >
            {{ t('knowledge.blueprints.stepper.next') }}
            <span class="icon-[lucide--chevron-right] ml-1" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <!-- 摘要事实（复用 buildStagePanorama 的产出） -->
      <dl
        v-if="activeNode.facts.length"
        class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"
        data-testid="blueprint-stepper-facts"
      >
        <div
          v-for="fact in activeNode.facts"
          :key="fact.key"
          class="inline-flex gap-1"
          data-testid="blueprint-stepper-fact"
          :data-fact="fact.key"
        >
          <dt>{{ factLabel(fact.key) }}</dt>
          <dd class="tabular-nums text-foreground">
            {{ fieldValue(fact.value) }}
          </dd>
        </div>
      </dl>

      <!-- 固定路由标注：全 0 证据在这种情况下是事实，不是缺陷 -->
      <p
        v-if="activeNode.pinnedRoute"
        class="mt-3 flex items-start gap-2 rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
        data-testid="blueprint-stepper-pinned"
      >
        <span class="icon-[lucide--pin] mt-0.5 shrink-0" aria-hidden="true" />
        <span>{{ t('knowledge.blueprints.activity.pinnedRoute') }}</span>
      </p>

      <div class="mt-4 space-y-4">
        <!-- ③ stage_state 分片（可读键值 + 折叠 JSON，⛔ 不整页倾倒） -->
        <section v-if="activeStageState" data-testid="blueprint-stepper-state">
          <h4 class="mb-2 text-sm font-medium text-muted-foreground">
            {{ t('knowledge.blueprints.stepper.stateTitle') }}
          </h4>
          <div class="rounded-lg border border-border/60 p-3 text-xs">
            <dl v-if="activeStageState.fields.length" class="flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
              <div v-for="field in activeStageState.fields" :key="field.key" class="inline-flex gap-1">
                <dt>{{ fieldLabel(field.key) }}</dt>
                <dd class="break-all tabular-nums text-foreground">
                  {{ fieldValue(field.value) }}
                </dd>
              </div>
            </dl>
            <div
              v-for="group in activeStageState.groups"
              :key="group.key"
              class="mt-1.5"
              data-testid="blueprint-stepper-state-group"
              :data-group="group.key"
            >
              <p class="flex items-center gap-1.5 text-muted-foreground">
                <span>{{ fieldLabel(group.key) }}</span>
                <Badge variant="muted" class="tabular-nums">
                  {{ t('knowledge.blueprints.activity.groupCount', { n: group.count }) }}
                </Badge>
              </p>
              <ul class="mt-0.5 space-y-0.5 border-l border-border/60 pl-2.5">
                <li v-for="(line, index) in group.lines" :key="index" class="break-all font-mono text-[11px] text-muted-foreground">
                  {{ line }}
                </li>
                <li v-if="group.truncated" class="text-[11px] text-muted-foreground/70">
                  {{ t('knowledge.blueprints.activity.groupTruncated') }}
                </li>
              </ul>
            </div>
            <template v-if="activeStageState.raw">
              <button
                type="button"
                class="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
                data-testid="blueprint-stepper-state-raw-toggle"
                @click="toggleRaw(`state:${activeStage}`)"
              >
                <span
                  class="icon-[lucide--chevron-right] transition-transform"
                  :class="rawOpen.has(`state:${activeStage}`) ? 'rotate-90' : ''"
                  aria-hidden="true"
                />
                {{ t('knowledge.blueprints.activity.rawToggle') }}
              </button>
              <pre
                v-if="rawOpen.has(`state:${activeStage}`)"
                class="mt-1 max-h-64 overflow-auto rounded-lg bg-muted/40 p-2 font-mono text-[11px] leading-relaxed"
                data-testid="blueprint-stepper-state-raw"
              >{{ activeStageState.raw }}</pre>
            </template>
          </div>
        </section>

        <!-- ④ 该节点的事件明细（复用既有事件过滤：panorama 节点已按 stage 聚好） -->
        <section data-testid="blueprint-stepper-events">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <h4 class="text-sm font-medium text-muted-foreground">
              {{ t('knowledge.blueprints.activity.eventsTitle') }}
            </h4>
            <!-- ⭐ 事件流只有阶段级标量；「agent 具体做了什么」在抽屉里。入口只挂在两个
                 起容器的节点上——其余阶段没有容器运行，点进去只会是空面板。 -->
            <button
              v-if="showResearchEntry"
              type="button"
              class="ml-auto inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              data-testid="blueprint-stepper-research-entry"
              @click="emit('view-research')"
            >
              <span class="icon-[lucide--list-tree]" aria-hidden="true" />
              {{ t('knowledge.blueprints.research.entry') }}
            </button>
          </div>
          <p v-if="!activeNode.events.length" class="text-xs text-muted-foreground">
            {{ t('knowledge.blueprints.stepper.eventsEmpty') }}
          </p>
          <ul v-else class="space-y-2">
            <li
              v-for="row in activeNode.events"
              :key="row.id"
              class="rounded-lg border border-border/60 p-3 text-xs"
              data-testid="blueprint-stepper-event"
              :data-event="row.event"
            >
              <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span class="text-sm font-medium text-foreground">{{ eventLabel(row) }}</span>
                <span class="tabular-nums text-muted-foreground">{{ formatTime(row.ts) }}</span>
                <code class="ml-auto text-[11px] text-muted-foreground/70">{{ row.event }}</code>
              </div>

              <dl v-if="row.fields.length" class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
                <div v-for="field in row.fields" :key="field.key" class="inline-flex gap-1">
                  <dt>{{ fieldLabel(field.key) }}</dt>
                  <dd class="break-all tabular-nums text-foreground">
                    {{ fieldValue(field.value) }}
                  </dd>
                </div>
              </dl>

              <div
                v-for="group in row.groups"
                :key="group.key"
                class="mt-1.5"
                data-testid="blueprint-stepper-event-group"
                :data-group="group.key"
              >
                <p class="flex items-center gap-1.5 text-muted-foreground">
                  <span>{{ fieldLabel(group.key) }}</span>
                  <Badge variant="muted" class="tabular-nums">
                    {{ t('knowledge.blueprints.activity.groupCount', { n: group.count }) }}
                  </Badge>
                </p>
                <ul class="mt-0.5 space-y-0.5 border-l border-border/60 pl-2.5">
                  <li v-for="(line, index) in group.lines" :key="index" class="break-all font-mono text-[11px] text-muted-foreground">
                    {{ line }}
                  </li>
                  <li v-if="group.truncated" class="text-[11px] text-muted-foreground/70">
                    {{ t('knowledge.blueprints.activity.groupTruncated') }}
                  </li>
                </ul>
              </div>

              <template v-if="row.raw">
                <button
                  type="button"
                  class="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
                  data-testid="blueprint-stepper-event-raw-toggle"
                  @click="toggleRaw(row.id)"
                >
                  <span
                    class="icon-[lucide--chevron-right] transition-transform"
                    :class="rawOpen.has(row.id) ? 'rotate-90' : ''"
                    aria-hidden="true"
                  />
                  {{ t('knowledge.blueprints.activity.rawToggle') }}
                </button>
                <pre
                  v-if="rawOpen.has(row.id)"
                  class="mt-1 max-h-64 overflow-auto rounded-lg bg-muted/40 p-2 font-mono text-[11px] leading-relaxed"
                  data-testid="blueprint-stepper-event-raw"
                >{{ row.raw }}</pre>
              </template>
            </li>
          </ul>
        </section>

        <!-- ⑤ 重跑历史（该节点有记录才渲染） -->
        <section v-if="activeRerunHistory.length" data-testid="blueprint-stepper-history">
          <h4 class="mb-2 text-sm font-medium text-muted-foreground">
            {{ t('knowledge.blueprints.rerun.historyTitle') }}
          </h4>
          <ul class="space-y-1.5">
            <li
              v-for="entry in activeRerunHistory"
              :key="`${entry.requested_at}-${entry.run_label}`"
              class="rounded-lg border border-border/60 p-2.5 text-xs"
              data-testid="blueprint-stepper-history-item"
            >
              <div class="flex flex-wrap items-center gap-2 text-muted-foreground">
                <Badge variant="muted" class="tabular-nums">
                  {{ t('knowledge.blueprints.stepper.runLabel', { label: entry.run_label }) }}
                </Badge>
                <span class="tabular-nums">{{ formatTime(entry.requested_at) }}</span>
              </div>
              <p v-if="entry.instruction" class="mt-1 wrap-break-word whitespace-pre-wrap text-foreground">
                {{ entry.instruction }}
              </p>
            </li>
          </ul>
        </section>

        <!-- ⑥ 带指令重跑表单（仅后端可重跑集合内 + 有会话时渲染） -->
        <section
          v-if="activeRerunStage"
          class="rounded-lg border border-border/60 bg-muted/20 p-3"
          data-testid="blueprint-stepper-rerun-form"
        >
          <h4 class="mb-2 flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
            <span class="icon-[lucide--rotate-ccw]" aria-hidden="true" />
            {{ t('knowledge.blueprints.rerun.title') }}
          </h4>
          <textarea
            v-model="instruction"
            rows="2"
            class="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40"
            :placeholder="t('knowledge.blueprints.rerun.placeholder')"
            data-testid="blueprint-stepper-rerun-input"
          />
          <div class="mt-2 flex justify-end">
            <Button
              variant="outline"
              size="sm"
              :disabled="submitting"
              data-testid="blueprint-stepper-rerun-submit"
              @click="submitRerun()"
            >
              <span
                :class="submitting ? 'icon-[lucide--loader-2] animate-spin' : 'icon-[lucide--rotate-ccw]'"
                class="mr-1.5"
                aria-hidden="true"
              />
              {{ t('knowledge.blueprints.rerun.submit') }}
            </Button>
          </div>
        </section>
      </div>
    </div>
  </section>
</template>
