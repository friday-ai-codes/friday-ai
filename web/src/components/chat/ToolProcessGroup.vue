<script setup lang="ts">
/**
 * Cursor 风格的「工作过程」折叠面板（用户诉求 1）+ open-webui 借鉴细节。
 *
 * 三层结构，默认全部收起：
 *   L0 收起：一行摘要（图标 + 标题 + 进度/耗时 + 最近一步预览）。
 *   L1 展开容器：依次列出每一步（思考 / 工具调用），grid-rows 动画展开。
 *   L2 展开单步：该步详情（工具输入/输出、相关性候选仓库编号 pill、思考全文）。
 *
 * 借鉴 open-webui：
 *   - 头部随状态变化（分析中 → 分析过程 · 用时 X），耗时人性化（humanizeDuration）。
 *   - 相关性候选用「编号 + 名称」来源式 pill 展示（对应 Citations.svelte）。
 *   - 工具步骤把 repository_id 渲染成「编号 + 仓库名称」（诉求 2/3）。
 *   - 外部可通过 expandSignal 触发展开 + 高亮（答案 → 证据闭环）。
 */
import {
  bareName,
  humanizeDuration,
  relevanceCandidates,
  routingDecisionView,
  toolAction,
  toolIcon,
  toolLabel,
} from '~/composables/useToolDisplay'
import RoutingCandidateList from './RoutingCandidateList.vue'
import StructuredJsonView from './StructuredJsonView.vue'

export interface ProcessThinkingStep {
  kind: 'thinking'
  id: string
  text: string
}
export interface ProcessToolStep {
  kind: 'tool'
  id: string
  name: string
  input: Record<string, unknown>
  result?: string
  status: 'running' | 'done'
}
export type ProcessStep = ProcessThinkingStep | ProcessToolStep

const props = withDefaults(defineProps<{
  steps: ProcessStep[]
  repoNames?: Record<string, string>
  /** repository_id → 会话级稳定编号（用于「编号来源」展示，诉求 3）。 */
  repoIndex?: Map<string, number>
  defaultExpanded?: boolean
  /** 供 ChatMessageBubble 标记定位（data-process-group）。 */
  groupId?: string
  /** 外部递增此值即触发展开 + 高亮闪烁（答案图例点击跳转）。 */
  expandSignal?: number
}>(), { defaultExpanded: true })

const expanded = ref(props.defaultExpanded)
/**
 * 行级折叠状态按步骤类型分开记账：
 * - thinking 行默认展开，`collapsedRows` 记录**被手动收起**的 id
 *   （不能用「展开集合」——步骤是流式追加的，后到的行不在集合里会退回收起）。
 * - tool 行沿用默认收起，`expandedRows` 记录被手动展开的 id。
 */
const collapsedRows = ref<Set<string>>(new Set())
const expandedRows = ref<Set<string>>(new Set())
const flashing = ref(false)

const isRunning = computed(() => props.steps.some(s => s.kind === 'tool' && s.status === 'running'))
const totalTools = computed(() => props.steps.filter(s => s.kind === 'tool').length)
const doneTools = computed(() => props.steps.filter(s => s.kind === 'tool' && s.status === 'done').length)

// ---- 耗时追踪（借鉴 open-webui reasoning duration）----
// 仅在本次会话里「亲历」运行 → 完成的过程才有耗时；历史消息无计时数据则省略。
const startedAt = ref<number | null>(null)
const durationSec = ref(0)
watch(isRunning, (running, prev) => {
  if (running && startedAt.value === null)
    startedAt.value = Date.now()
  if (!running && prev && startedAt.value !== null && durationSec.value === 0)
    durationSec.value = (Date.now() - startedAt.value) / 1000
}, { immediate: true })

// ---- 自动展开（流式期间）/ 外部跳转展开 ----
const userToggled = ref(false)
watch(() => props.steps.map(s => (s.kind === 'tool' ? s.status : 'thinking')).join(','), () => {
  if (!userToggled.value && isRunning.value)
    expanded.value = true
})
let flashTimer: ReturnType<typeof setTimeout> | null = null
watch(() => props.expandSignal, (val, old) => {
  if (val === undefined || val === old || val === 0)
    return
  expanded.value = true
  flashing.value = true
  if (flashTimer)
    clearTimeout(flashTimer)
  flashTimer = setTimeout(() => (flashing.value = false), 1300)
})
onBeforeUnmount(() => {
  if (flashTimer)
    clearTimeout(flashTimer)
})

function toggleContainer() {
  userToggled.value = true
  expanded.value = !expanded.value
}
function rowExpanded(step: ProcessStep): boolean {
  if (step.kind === 'thinking')
    return !collapsedRows.value.has(step.id)
  return expandedRows.value.has(step.id)
}
function toggleRow(step: ProcessStep) {
  const bucket = step.kind === 'thinking' ? collapsedRows : expandedRows
  if (bucket.value.has(step.id))
    bucket.value.delete(step.id)
  else
    bucket.value.add(step.id)
}

const headerTitle = computed(() => (isRunning.value ? '分析中' : '分析过程'))
const headerMeta = computed(() => {
  if (isRunning.value)
    return totalTools.value > 0 ? `已完成 ${doneTools.value}/${totalTools.value} 步` : '进行中'
  const dur = humanizeDuration(durationSec.value)
  return dur ? `${totalTools.value} 步 · 用时 ${dur}` : `${totalTools.value} 步`
})

function stepLabel(step: ProcessStep): string {
  return step.kind === 'thinking' ? '思考' : toolLabel(step.name)
}
function stepIcon(step: ProcessStep): string {
  return step.kind === 'thinking' ? 'icon-[lucide--sparkles]' : toolIcon(step.name)
}
function stepText(step: ProcessStep): string {
  if (step.kind === 'thinking') {
    const firstLine = step.text.trim().split('\n')[0] || ''
    return firstLine.length > 90 ? `${firstLine.slice(0, 90)}…` : firstLine
  }
  return toolAction(step.name, step.input || {}, step.result, props.repoNames)
}
function isRelevanceStep(step: ProcessStep): boolean {
  return step.kind === 'tool' && bareName(step.name) === 'analyze_repository_relevance'
}
function rowExpandable(step: ProcessStep): boolean {
  // 思考行恒可切换：行头只是 90 字符单行摘要，短思考同样需要能看到全文。
  if (step.kind === 'thinking')
    return true
  if (isRelevanceStep(step) && relevanceCandidates(step.result).length > 0)
    return true
  const hasInput = !!(step.input && Object.keys(step.input).length > 0)
  return hasInput || !!step.result
}

/** 工具步骤命中的仓库编号（搜索/浏览/仓库信息等带 repository_id 的工具）。 */
function stepRepoNumber(step: ProcessStep): number | null {
  if (step.kind !== 'tool')
    return null
  const rid = (step.input?.repository_id as string) || ''
  if (!rid)
    return null
  return props.repoIndex?.get(rid) ?? null
}

/** 路由决策视图（分组 / 跨组 / 分数分解 / 降级四层事实的单一来源）。 */
function routingViewOf(step: ProcessStep) {
  return routingDecisionView(step.kind === 'tool' ? step.result : undefined)
}

const lastStepText = computed(() => {
  if (props.steps.length === 0)
    return ''
  return stepText(props.steps[props.steps.length - 1])
})
</script>

<template>
  <div
    class="tpg"
    :class="{ 'tpg--running': isRunning, 'tpg--flash': flashing }"
    :data-process-group="groupId"
  >
    <button class="tpg-head" type="button" :aria-expanded="expanded" @click="toggleContainer">
      <span class="tpg-status">
        <span v-if="isRunning" class="tpg-spinner" />
        <span v-else class="tpg-dot tpg-dot--done" />
      </span>
      <span class="tpg-title">{{ headerTitle }}</span>
      <span class="tpg-meta">{{ headerMeta }}</span>
      <span v-if="!expanded && lastStepText" class="tpg-preview">{{ lastStepText }}</span>
      <span
        class="icon-[lucide--chevron-right] tpg-caret"
        :class="expanded ? 'rotate-90' : ''"
      />
    </button>

    <!-- L1 列表：grid-rows 0fr→1fr 平滑展开（借鉴 open-webui Collapsible grow 模式） -->
    <div class="tpg-collapse" :class="{ 'is-open': expanded }">
      <div class="tpg-collapse-inner">
        <div class="tpg-list">
          <div
            v-for="step in steps"
            :key="step.id"
            class="tpg-row"
            :class="[`tpg-row--${step.kind}`, { 'is-open': rowExpanded(step) }]"
          >
            <button
              type="button"
              class="tpg-row-head"
              :class="{ 'is-interactive': rowExpandable(step) }"
              :disabled="!rowExpandable(step)"
              @click="rowExpandable(step) && toggleRow(step)"
            >
              <span class="tpg-row-rail">
                <span
                  v-if="step.kind === 'tool' && step.status === 'running'"
                  class="tpg-spinner tpg-spinner--sm"
                />
                <span v-else :class="stepIcon(step)" class="tpg-row-icon" />
              </span>
              <span v-if="stepRepoNumber(step) !== null" class="tpg-num">{{ stepRepoNumber(step) }}</span>
              <span class="tpg-row-label">{{ stepLabel(step) }}</span>
              <span class="tpg-row-text">{{ stepText(step) }}</span>
              <span
                v-if="rowExpandable(step)"
                class="icon-[lucide--chevron-right] tpg-row-caret"
                :class="rowExpanded(step) ? 'rotate-90' : ''"
              />
            </button>

            <div v-if="rowExpanded(step)" class="tpg-detail">
              <!-- 思考全文 -->
              <p v-if="step.kind === 'thinking'" class="tpg-thinking">
                {{ step.text.trim() }}
              </p>

              <template v-else-if="step.kind === 'tool'">
                <!--
                  相关性分析：分组 / 跨组标注 / 分数分解 / 降级横幅
                  （ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03）。
                  这是这四条需求**唯一**到达用户的渲染面 —— 原承载者
                  RoutingDecisionPanel 已无挂载点，见该组件头注释。
                -->
                <template v-if="isRelevanceStep(step)">
                  <RoutingCandidateList :view="routingViewOf(step)" :repo-index="repoIndex" />
                  <div v-if="step.input && Object.keys(step.input).length > 0" class="tpg-detail-section">
                    <span class="tpg-detail-label">输入</span>
                    <StructuredJsonView :value="step.input" :tool-name="step.name" kind="input" />
                  </div>
                </template>

                <!-- 普通工具：输入 / 输出 -->
                <template v-else>
                  <div v-if="step.input && Object.keys(step.input).length > 0" class="tpg-detail-section">
                    <span class="tpg-detail-label">输入</span>
                    <StructuredJsonView :value="step.input" :tool-name="step.name" kind="input" />
                  </div>
                  <div v-if="step.result" class="tpg-detail-section">
                    <span class="tpg-detail-label">输出</span>
                    <StructuredJsonView :value="step.result" :tool-name="step.name" kind="output" />
                  </div>
                </template>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tpg {
  border-radius: 0.625rem;
  border: 1px solid hsl(214 32% 91% / 0.7);
  background: hsl(210 40% 98% / 0.5);
  overflow: hidden;
  transition:
    box-shadow 0.2s ease,
    border-color 0.2s ease;
}
.tpg--running {
  border-color: hsl(168 76% 42% / 0.3);
  background: hsl(168 76% 97% / 0.45);
}
.tpg--flash {
  border-color: hsl(168 76% 42% / 0.6);
  animation: tpg-flash 1.3s ease;
}
@keyframes tpg-flash {
  0%,
  100% {
    box-shadow: 0 0 0 0 hsl(168 76% 42% / 0);
  }
  20% {
    box-shadow: 0 0 0 3px hsl(168 76% 42% / 0.25);
  }
}

/* ---- L0：摘要头 ---- */
.tpg-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.4375rem 0.625rem;
  border: 0;
  background: transparent;
  text-align: left;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.tpg-head:hover {
  background: hsl(210 40% 95% / 0.6);
}

.tpg-status {
  display: inline-flex;
  flex-shrink: 0;
}

.tpg-title {
  flex-shrink: 0;
  font-size: 0.75rem;
  font-weight: 600;
  color: hsl(215 28% 22%);
}

.tpg-meta {
  flex-shrink: 0;
  font-size: 0.625rem;
  padding: 0.0625rem 0.4375rem;
  border-radius: 9999px;
  background: hsl(215 16% 47% / 0.1);
  color: hsl(215 16% 45%);
  font-variant-numeric: tabular-nums;
}

.tpg-preview {
  flex: 1;
  min-width: 0;
  font-size: 0.6875rem;
  color: hsl(215 16% 50% / 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tpg-caret {
  flex-shrink: 0;
  margin-left: auto;
  font-size: 10px;
  color: hsl(215 16% 60% / 0.7);
  transition: transform 0.15s ease;
}
.tpg-preview + .tpg-caret {
  margin-left: 0;
}

/* ---- L1：grid-rows 折叠动画 ---- */
.tpg-collapse {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.24s ease-out;
}
.tpg-collapse.is-open {
  grid-template-rows: 1fr;
}
.tpg-collapse-inner {
  overflow: hidden;
  min-height: 0;
}

.tpg-list {
  padding: 0.1875rem 0.375rem 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.tpg-row {
  border-radius: 0.4375rem;
}
.tpg-row.is-open {
  background: hsl(210 40% 96% / 0.55);
}

.tpg-row-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.3125rem 0.5rem;
  border: 0;
  border-radius: 0.4375rem;
  background: transparent;
  text-align: left;
  font-family: inherit;
  color: hsl(215 16% 35%);
  transition: background-color 0.12s ease;
}
.tpg-row-head.is-interactive {
  cursor: pointer;
}
.tpg-row-head.is-interactive:hover {
  background: hsl(210 40% 96% / 0.7);
}
.tpg-row-head:disabled {
  cursor: default;
}

.tpg-row-rail {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  flex-shrink: 0;
}
.tpg-row-icon {
  font-size: 12px;
  color: hsl(215 16% 50% / 0.8);
}

.tpg-row-label {
  flex-shrink: 0;
  font-size: 0.6875rem;
  font-weight: 600;
  color: hsl(215 28% 28%);
}

.tpg-row-text {
  flex: 1;
  min-width: 0;
  font-size: 0.6875rem;
  color: hsl(215 16% 42%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tpg-row-caret {
  flex-shrink: 0;
  font-size: 9px;
  color: hsl(215 16% 60% / 0.6);
  transition: transform 0.15s ease;
}

.tpg-row--thinking .tpg-row-icon {
  color: hsl(168 76% 42%);
}
.tpg-row--thinking .tpg-row-label {
  color: hsl(168 70% 32%);
}

/* 编号徽标（来源式编号，借鉴 open-webui Citations） */
.tpg-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 1.05rem;
  height: 1.05rem;
  padding: 0 0.25rem;
  border-radius: 9999px;
  background: hsl(168 76% 42% / 0.14);
  color: hsl(168 70% 30%);
  font-size: 0.5625rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

/* ---- L2：单步详情 ---- */
.tpg-detail {
  margin: 0 0.5rem 0.375rem 1.5rem;
  padding: 0.375rem 0.5rem;
  border-left: 2px solid hsl(214 32% 91% / 0.7);
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.tpg-thinking {
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.6;
  color: hsl(215 16% 35%);
  font-style: italic;
  white-space: pre-wrap;
  word-break: break-word;
}

.tpg-detail-section {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}
.tpg-detail-label {
  font-size: 0.5625rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: hsl(215 16% 47% / 0.5);
}

/* dot / spinner */
.tpg-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tpg-dot--done {
  background: hsl(142 71% 45%);
}
.tpg-spinner {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 1.5px solid hsl(168 76% 42% / 0.25);
  border-top-color: hsl(168 76% 42%);
  animation: tpg-spin 0.7s linear infinite;
  flex-shrink: 0;
}
.tpg-spinner--sm {
  width: 9px;
  height: 9px;
  border-width: 1.25px;
}
@keyframes tpg-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tpg-collapse {
    transition: none;
  }
  .tpg-spinner {
    animation-duration: 1.4s;
  }
}

.dark .tpg {
  border-color: hsl(214 32% 20% / 0.6);
  background: hsl(220 20% 12% / 0.4);
}
.dark .tpg-title {
  color: hsl(215 16% 80%);
}
.dark .tpg-row-head {
  color: hsl(215 16% 70%);
}
.dark .tpg-row-label {
  color: hsl(215 16% 78%);
}
</style>
