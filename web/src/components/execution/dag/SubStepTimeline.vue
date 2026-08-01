<script setup lang="ts">
/**
 * SubStepTimeline — 通用竖向步骤时间线
 *
 * 左侧垂直连线 + 状态圆点，右侧步骤名称，类似 GitHub Actions 风格。
 * 同时服务两个域：`ExecutionNode` 展开区域内的 AI 节点子步骤，以及 chat 侧的方案编排阶段。
 *
 * 🔴 本组件的泛化是**纯加性**的：`interactive` / `statusText` 两个 prop 与
 * `summary` / `badge` / `pulse` 三个 item 字段全部可选，缺省时渲染结果与泛化前逐字一致，
 * `ExecutionNode` 的调用点一个字都不用改。
 */
import type { TimelineStepItem } from '~/types/execution'
import { Badge } from '~/components/ui/badge'

const props = withDefaults(defineProps<{
  steps: TimelineStepItem[]
  /** 是否可点击。默认 true = 今日行为逐字不变；chat 侧传 false。 */
  interactive?: boolean
  /** 每个状态的中文文本（供 sr-only 与 title），缺省用内置默认。 */
  statusText?: Partial<Record<TimelineStepItem['status'], string>>
}>(), { interactive: true })

const emit = defineEmits<{
  stepClick: [stepId: string]
}>()

const DEFAULT_STATUS_TEXT: Record<TimelineStepItem['status'], string> = {
  pending: '未开始',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
  skipped: '已跳过',
  unknown: '进度未知',
}

/**
 * 状态点样式。
 *
 * skipped / unknown 走空心点：色 token 与 pending 同族，靠**边框 vs 实心的形状差异**区分，
 * 与颜色无关 —— 这是「不靠颜色单独传达状态」的第一重保障。两者共用同一视觉、
 * 靠摘要文案区分（`已跳过` / `进度未知`），因为它们都不是错误态：
 * 把「不知道」画成「失败」是撒谎。
 */
function stepStatusColor(step: TimelineStepItem): string {
  const map: Record<string, string> = {
    pending: 'bg-muted-foreground/50',
    running: 'bg-primary animate-pulse',
    completed: 'bg-emerald-400',
    failed: 'bg-red-400',
    skipped: 'bg-transparent border border-muted-foreground/50',
    unknown: 'bg-transparent border border-muted-foreground/50',
  }
  // 显式 pulse:false ⇒ 只去掉 animate-pulse，色值一字不改。缺省 / 非 false 仍是既有取值。
  if (step.status === 'running' && step.pulse === false)
    return 'bg-primary'
  return map[step.status] ?? 'bg-muted-foreground/50'
}

function statusLabel(status: string): string {
  const key = status as TimelineStepItem['status']
  return props.statusText?.[key] ?? DEFAULT_STATUS_TEXT[key] ?? DEFAULT_STATUS_TEXT.unknown
}

/**
 * 摘要行是否渲染。
 * `summary` 存在即渲染；否则回退既有「failed 且有 output_data.error」路径（逐字保留）。
 */
function hasSummary(step: TimelineStepItem): boolean {
  return Boolean(step.summary) || (step.status === 'failed' && Boolean(step.output_data?.error))
}

/**
 * 摘要文案。`summary` 优先，缺失才回退既有 `output_data.error` 的 50 字截断。
 *
 * 🔴 失败摘要行只挂 `role="alert"`，整个组件不得出现 `aria-live`：本组件是被别人嵌进去的，
 * 播报归属由外层卡片的单一 live region 决定（110-06 §A.6），在这里加会「一个事实播多次」。
 * 注意该字样不能出现在 <template> 的注释里 —— 非生产构建下模板注释会保留进渲染结果。
 */
function summaryText(step: TimelineStepItem): string {
  if (step.summary)
    return step.summary
  return typeof step.output_data?.error === 'string' ? step.output_data.error.slice(0, 50) : ''
}

function onRowClick(event: MouseEvent, step: TimelineStepItem) {
  event.stopPropagation()
  emit('stepClick', step.id)
}
</script>

<template>
  <div class="mt-2 pl-1" role="list">
    <TransitionGroup
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
    >
      <div
        v-for="(step, index) in steps"
        :key="step.id"
        role="listitem"
        class="relative flex items-start gap-2 rounded px-1 py-0.5 transition-colors"
        :class="interactive ? 'cursor-pointer hover:bg-muted/30' : undefined"
        :title="statusLabel(step.status)"
        v-on="interactive ? { click: (e: MouseEvent) => onRowClick(e, step) } : {}"
      >
        <!-- 垂直连线（除最后一个） -->
        <div
          v-if="index < steps.length - 1"
          class="absolute left-[7px] top-4 w-px h-[calc(100%)] bg-border/50"
        />
        <!-- 状态圆点 -->
        <div
          class="relative z-10 mt-1 w-2.5 h-2.5 rounded-full shrink-0 transition-colors duration-300"
          :class="stepStatusColor(step)"
        />
        <!-- 可读状态文本：状态不只由圆点颜色传达 -->
        <span class="sr-only">{{ statusLabel(step.status) }}</span>
        <!-- 步骤名称 + 摘要 -->
        <div class="flex-1 min-w-0">
          <span
            class="text-[11px] leading-tight block truncate"
            :class="step.status === 'failed' ? 'text-red-400' : 'text-muted-foreground'"
          >
            {{ step.name }}
          </span>
          <!-- 摘要行：failed 只用 role=alert，不带实时播报属性（见 script 段注释） -->
          <span
            v-if="hasSummary(step)"
            class="text-[10px] truncate block"
            :class="step.status === 'failed' ? 'text-red-400/70' : 'text-muted-foreground'"
            :role="step.status === 'failed' ? 'alert' : undefined"
          >
            {{ summaryText(step) }}
          </span>
        </div>
        <!-- 行尾角标（纯 variant，禁止 :class 追加颜色） -->
        <Badge v-if="step.badge" :variant="step.badge.variant" class="shrink-0 mt-0.5">
          {{ step.badge.text }}
        </Badge>
      </div>
    </TransitionGroup>
  </div>
</template>
