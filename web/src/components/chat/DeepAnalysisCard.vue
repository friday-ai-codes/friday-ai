<script setup lang="ts">
/**
 * 单个深度分析子代理（subagent）的执行记录面板。
 *
 * 头部展示任务描述 + 状态 + 日志条数；正文逐行展示思考 / 工具调用 / 结果。
 * 工具调用参数用 StructuredJsonView 结构化展开，不再裸 JSON 换行（第 3 点）。
 */
import type { DeepAnalysisSession } from '~/types/chat'
import { decorateDeepLog, isLongText, previewText } from '~/composables/useDeepAnalysisLog'
import StructuredJsonView from './StructuredJsonView.vue'

const props = withDefaults(defineProps<{
  session: DeepAnalysisSession
  taskLabel?: string
  status?: 'running' | 'done'
  defaultExpanded?: boolean
}>(), { defaultExpanded: true })

const expanded = ref(props.defaultExpanded)
const expandedRows = ref<Set<number>>(new Set())

function toggleRow(i: number) {
  if (expandedRows.value.has(i))
    expandedRows.value.delete(i)
  else
    expandedRows.value.add(i)
}

// 预先解码并保留稳定索引（过滤掉 null 的噪音行）
const rows = computed(() => {
  const out: Array<{ idx: number, view: NonNullable<ReturnType<typeof decorateDeepLog>> }> = []
  props.session.logs.forEach((log, i) => {
    const view = decorateDeepLog(log)
    if (view)
      out.push({ idx: i, view })
  })
  return out
})

const headerTitle = computed(() => props.taskLabel || props.session.task_description || '执行记录')
const isRunning = computed(() => props.status === 'running' || props.session.status === 'RUNNING' || props.session.status === 'PENDING')

function rowIsInteractive(view: NonNullable<ReturnType<typeof decorateDeepLog>>): boolean {
  return view.expandable || isLongText(view.text)
}
</script>

<template>
  <div class="da-card" :class="{ 'da-card--running': isRunning }">
    <button class="da-head" type="button" @click="expanded = !expanded">
      <span class="da-status">
        <span v-if="isRunning" class="da-dot da-dot--running" />
        <span v-else class="da-dot da-dot--done" />
      </span>
      <span class="da-title" :title="headerTitle">{{ headerTitle }}</span>
      <span class="da-count">{{ rows.length }} 步</span>
      <span
        class="icon-[lucide--chevron-right] da-caret"
        :class="expanded ? 'rotate-90' : ''"
      />
    </button>

    <div v-if="expanded" class="da-logs">
      <p v-if="rows.length === 0" class="da-empty">
        {{ isRunning ? '正在执行…' : '暂无执行记录' }}
      </p>
      <component
        :is="rowIsInteractive(row.view) ? 'button' : 'div'"
        v-for="row in rows"
        :key="row.idx"
        class="da-row"
        :class="[
          `da-row--${row.view.kind}`,
          { 'is-interactive': rowIsInteractive(row.view), 'is-open': expandedRows.has(row.idx) },
        ]"
        :type="rowIsInteractive(row.view) ? 'button' : undefined"
        @click="rowIsInteractive(row.view) && toggleRow(row.idx)"
      >
        <span :class="row.view.icon" class="da-row-icon" />
        <div class="da-row-body">
          <div class="da-row-head">
            <span v-if="row.view.label" class="da-row-label">{{ row.view.label }}</span>
            <span
              class="da-row-text"
              :class="{ 'da-row-text--clamp': isLongText(row.view.text) && !expandedRows.has(row.idx) }"
            >
              {{ isLongText(row.view.text) && !expandedRows.has(row.idx) ? previewText(row.view.text) : row.view.text }}
            </span>
            <span
              v-if="rowIsInteractive(row.view)"
              class="icon-[lucide--chevron-right] da-row-caret"
              :class="expandedRows.has(row.idx) ? 'rotate-90' : ''"
            />
          </div>
          <div v-if="row.view.expandable && expandedRows.has(row.idx)" class="da-row-detail">
            <StructuredJsonView
              :value="row.view.detailValue ?? row.view.detail"
              :tool-name="row.view.toolName"
              kind="input"
            />
          </div>
        </div>
      </component>
    </div>
  </div>
</template>

<style scoped>
.da-card {
  border-radius: 0.625rem;
  border: 1px solid hsl(214 32% 91% / 0.7);
  background: hsl(210 40% 98% / 0.5);
  overflow: hidden;
}
.da-card--running {
  border-color: hsl(168 76% 42% / 0.3);
  background: hsl(168 76% 97% / 0.45);
}

.da-head {
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
.da-head:hover {
  background: hsl(210 40% 95% / 0.6);
}

.da-status {
  display: inline-flex;
  flex-shrink: 0;
}
.da-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.da-dot--running {
  background: hsl(168 76% 42%);
  animation: da-pulse 1.5s infinite;
}
.da-dot--done {
  background: hsl(142 71% 45%);
}

.da-title {
  flex: 1;
  min-width: 0;
  font-size: 0.75rem;
  font-weight: 600;
  color: hsl(215 28% 22%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.da-count {
  flex-shrink: 0;
  font-size: 0.625rem;
  padding: 0.0625rem 0.4375rem;
  border-radius: 9999px;
  background: hsl(215 16% 47% / 0.1);
  color: hsl(215 16% 45%);
  font-variant-numeric: tabular-nums;
}

.da-caret {
  flex-shrink: 0;
  font-size: 10px;
  color: hsl(215 16% 60% / 0.7);
  transition: transform 0.15s ease;
}

.da-logs {
  padding: 0.25rem 0.375rem 0.375rem;
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 22rem;
  overflow-y: auto;
}

.da-empty {
  margin: 0;
  padding: 0.5rem 0.5rem;
  font-size: 0.6875rem;
  color: hsl(215 16% 55%);
}

/* ---- 单行日志 ---- */
.da-row {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  width: 100%;
  padding: 0.3125rem 0.5rem;
  border: 0;
  border-radius: 0.375rem;
  background: transparent;
  text-align: left;
  font-family: inherit;
  color: hsl(215 16% 35%);
  transition: background-color 0.12s ease;
}
.da-row.is-interactive {
  cursor: pointer;
}
.da-row.is-interactive:hover {
  background: hsl(210 40% 96% / 0.7);
}
.da-row.is-open {
  background: hsl(210 40% 96% / 0.55);
}

.da-row-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 0.9375rem;
  height: 1.1rem;
  font-size: 11px;
  color: hsl(215 16% 50% / 0.7);
  flex-shrink: 0;
}

.da-row-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3125rem;
}

.da-row-head {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  min-width: 0;
}

.da-row-label {
  flex-shrink: 0;
  font-size: 0.625rem;
  font-weight: 600;
  padding: 0.0625rem 0.375rem;
  border-radius: 0.3125rem;
  background: hsl(215 16% 47% / 0.1);
  color: hsl(215 28% 32%);
}

.da-row-text {
  flex: 1;
  min-width: 0;
  font-size: 0.75rem;
  line-height: 1.55;
  color: hsl(215 16% 38%);
  white-space: pre-wrap;
  word-break: break-word;
}
.da-row-text--clamp {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.da-row-caret {
  flex-shrink: 0;
  font-size: 10px;
  color: hsl(215 16% 60% / 0.7);
  transition: transform 0.15s ease;
  align-self: center;
}

.da-row-detail {
  padding-bottom: 0.1875rem;
}

/* ---- kind 着色 ---- */
.da-row--thinking .da-row-icon {
  color: hsl(168 76% 42%);
}
.da-row--thinking .da-row-label {
  background: hsl(168 76% 42% / 0.12);
  color: hsl(168 70% 30%);
}
.da-row--thinking .da-row-text {
  color: hsl(215 16% 35%);
  font-style: italic;
}

.da-row--tool .da-row-icon {
  color: hsl(217 91% 60%);
}
.da-row--tool .da-row-label {
  background: hsl(217 91% 60% / 0.12);
  color: hsl(217 70% 42%);
}
.da-row--tool .da-row-text {
  font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
  font-size: 0.6875rem;
  color: hsl(215 28% 28%);
}

.da-row--result .da-row-icon {
  color: hsl(142 71% 45%);
}
.da-row--result .da-row-text {
  color: hsl(142 50% 30%);
  font-weight: 500;
}

.da-row--error .da-row-icon {
  color: hsl(0 72% 51%);
}
.da-row--error .da-row-text {
  color: hsl(0 60% 40%);
}

.da-row--progress .da-row-icon {
  color: hsl(38 92% 50%);
  animation: da-pulse 1.6s infinite;
}

@keyframes da-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

.dark .da-card {
  border-color: hsl(214 32% 20% / 0.6);
  background: hsl(220 20% 12% / 0.4);
}
.dark .da-title {
  color: hsl(215 16% 80%);
}
.dark .da-row {
  color: hsl(215 16% 70%);
}
</style>
