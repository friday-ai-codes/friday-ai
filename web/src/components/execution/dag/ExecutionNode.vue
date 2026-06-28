<script setup lang="ts">
import type { ExecutionNodeData } from './composables/useExecutionDag'
import type { SubStep } from '~/types/execution'
/**
 * ExecutionNode — 只读执行节点组件
 *
 * 基于 BaseWorkflowNode 的视觉风格，但独立实现（不包含编辑器逻辑）。
 * 显示图标 + 名称 + 状态色边框 + 耗时标签 + 瓶颈标记 + AI 成本徽章。
 */
import { Handle, Position } from '@vue-flow/core'
import { computed, ref } from 'vue'
import Badge from '~/components/ui/badge/Badge.vue'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useNodeStyle } from '~/components/workflow/editor/nodes/composables/useNodeStyle'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
import { LIFECYCLE_VISUALS, lifecycleBadgeText, normalizeLifecyclePhase } from './composables/lifecycleBadge'
import SubStepTimeline from './SubStepTimeline.vue'

const props = defineProps<{
  id: string
  data: ExecutionNodeData
}>()

const visual = computed(() => getNodeVisual(props.data.nodeType))
const style = computed(() => useNodeStyle(visual.value.color).value)

/** 执行状态 → 边框色映射（覆盖默认的节点类型色） */
const statusBorderClass = computed(() => {
  // 调试暂停优先于普通状态色
  if (props.data.isDebugPaused) {
    return 'border-amber-400/70 node-debug-paused-border'
  }
  const map: Record<string, string> = {
    running: 'border-primary/80 node-running-border',
    completed: 'border-green-400/60',
    failed: 'border-red-400/70',
    pending: 'border-border/50',
    skipped: 'border-border/30 opacity-50',
    waiting_approval: 'border-orange-400/60',
    waiting_event: 'border-indigo-400/60',
    paused: 'border-yellow-400/60',
    cancelled: 'border-border/50',
    // OBS-03：防御性补 suspended/timeout 色（DAG 渲染 NodeExecution，理论无 suspended，补色避免 fallback）
    suspended: 'border-purple-400/60',
    timeout: 'border-rose-400/60',
  }
  return map[props.data.status] ?? 'border-border/50'
})

// P5：节点生命周期相位徽章（相位 + 收敛轮次）。idle 不展示以免污染待运行节点。
const lifecyclePhase = computed(() => normalizeLifecyclePhase(props.data.lifecycle))
const showLifecycleBadge = computed(() => lifecyclePhase.value !== 'idle')
const lifecycleVisual = computed(() => LIFECYCLE_VISUALS[lifecyclePhase.value])
const lifecycleText = computed(() =>
  lifecycleBadgeText(lifecyclePhase.value, props.data.round, props.data.maxRounds),
)

// OBS-01：失败节点 error 摘要（最小实现，供 tooltip 展示；富交互留 v2）
const failedErrorMessage = computed(() => {
  if (props.data.status !== 'failed')
    return ''
  return props.data.nodeExecution?.error_message ?? ''
})

/** 瓶颈光晕 — 用 shadow + ring 避免与状态色 border 冲突 */
const bottleneckClass = computed(() => {
  if (!props.data.isBottleneck)
    return ''
  return props.data.bottleneckLevel === 'critical'
    ? 'shadow-[0_0_12px_rgba(239,68,68,0.4)] ring-2 ring-red-400/50'
    : 'shadow-[0_0_10px_rgba(234,179,8,0.35)] ring-2 ring-yellow-400/50'
})

const durationText = computed(() => {
  const seconds = props.data.elapsed ?? props.data.duration
  if (seconds == null)
    return '-'
  if (seconds < 60)
    return `${Math.round(seconds)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
})

/** 状态指示点颜色 */
const statusDotClass = computed(() => {
  if (props.data.isDebugPaused) {
    return 'bg-amber-400 animate-pulse'
  }
  const map: Record<string, string> = {
    running: 'bg-primary animate-pulse',
    completed: 'bg-green-400',
    failed: 'bg-red-400',
    pending: 'bg-muted-foreground/50',
    skipped: 'bg-muted-foreground/50',
    waiting_approval: 'bg-orange-400 animate-pulse',
    waiting_event: 'bg-indigo-400 animate-pulse',
    paused: 'bg-yellow-400',
    cancelled: 'bg-muted-foreground/50',
    suspended: 'bg-purple-400 animate-pulse',
    timeout: 'bg-rose-400',
  }
  return map[props.data.status] ?? 'bg-muted-foreground/50'
})

/** 成本格式化 */
const costFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
})

const costText = computed(() => {
  if (!props.data.cost)
    return ''
  const val = Number.parseFloat(props.data.cost.totalCostUsd)
  if (Number.isNaN(val) || val === 0)
    return '$0.00'
  return costFormatter.format(val)
})

function formatTokenCount(count: number): string {
  if (count >= 1_000_000)
    return `${(count / 1_000_000).toFixed(1)}M`
  if (count >= 1_000)
    return `${(count / 1_000).toFixed(1)}k`
  return String(count)
}

// 子步骤展开/折叠
const store = useExecutionsStore()
const expanded = ref(false)

const nodeSubSteps = computed<SubStep[]>(() => {
  const neId = props.data.nodeExecution?.id
  if (!neId)
    return []
  return store.subSteps[neId] ?? []
})

const hasSubSteps = computed(() =>
  props.data.isAINode && props.data.subStepProgress != null && props.data.subStepProgress.total > 0,
)

const progressText = computed(() => {
  const p = props.data.subStepProgress
  if (!p)
    return ''
  return `${p.completed}/${p.total} steps`
})

function toggleExpand() {
  expanded.value = !expanded.value
  if (expanded.value && nodeSubSteps.value.length === 0 && props.data.nodeExecution?.id) {
    store.fetchSubSteps(props.data.nodeExecution.id)
  }
}

function handleSubStepClick(stepId: string) {
  props.data.onSubStepClick?.(props.data.nodeExecution?.id ?? '', stepId)
}
</script>

<template>
  <div>
    <Handle type="target" :position="Position.Top" />

    <div
      class="group w-[200px] bg-card/80 backdrop-blur-sm border rounded-2xl p-3 transition-all duration-200 cursor-pointer hover:shadow-md hover:border-opacity-70"
      :class="[statusBorderClass, bottleneckClass]"
    >
      <!-- 头部：断点指示器 + 图标 + 名称 -->
      <div class="flex items-center gap-2 mb-1.5">
        <!-- : 断点指示器 -->
        <div
          v-if="data.isDebugExecution"
          class="shrink-0 flex items-center justify-center w-4 h-4 cursor-pointer"
          @click.stop="data.onToggleBreakpoint?.(props.id)"
        >
          <div
            v-if="data.hasBreakpoint"
            class="w-2.5 h-2.5 rounded-full bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.5)]"
          />
          <div
            v-else
            class="w-2.5 h-2.5 rounded-full border border-gray-400/50 opacity-0 group-hover:opacity-60 transition-opacity"
          />
        </div>
        <div class="bg-gradient-to-br rounded-lg p-1.5" :class="[style.iconBg]">
          <component :is="visual.icon" class="w-4 h-4" :class="style.iconColor" />
        </div>
        <span class="text-sm font-medium text-foreground truncate flex-1">
          {{ data.name }}
        </span>
        <!-- 状态指示点（OBS-01：失败节点 tooltip 展示 error_message） -->
        <TooltipProvider v-if="failedErrorMessage">
          <Tooltip>
            <TooltipTrigger as-child>
              <div class="w-2 h-2 rounded-full shrink-0 cursor-help" :class="statusDotClass" />
            </TooltipTrigger>
            <TooltipContent side="bottom" class="max-w-xs">
              <span class="text-xs wrap-break-word">{{ failedErrorMessage }}</span>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <div v-else class="w-2 h-2 rounded-full shrink-0" :class="statusDotClass" />
      </div>

      <!-- P5：生命周期相位徽章（相位语义色 + 收敛轮次文案） -->
      <div
        v-if="showLifecycleBadge"
        class="mb-1.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium leading-none"
        :class="lifecycleVisual.badgeClass"
      >
        <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="lifecycleVisual.dotClass" />
        <span class="truncate">{{ lifecycleText }}</span>
      </div>

      <!-- 底部：耗时 + 从此继续按钮 + 成本徽章 + 瓶颈标签 -->
      <div class="flex items-center justify-between text-xs text-muted-foreground">
        <span class="tabular-nums">{{ durationText }}</span>

        <div class="flex items-center gap-1">
          <!-- 调试暂停节点：放行/跳过操作按钮 -->
          <template v-if="data.isDebugPaused">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger as-child>
                  <button
                    class="inline-flex items-center justify-center rounded-md transition-colors w-5 h-5 text-emerald-500 hover:bg-emerald-500/10 cursor-pointer"
                    @click.stop="data.onDebugRelease?.(props.id)"
                  >
                    <span class="icon-[lucide--play] w-3.5 h-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  放行此节点
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger as-child>
                  <button
                    class="inline-flex items-center justify-center rounded-md transition-colors w-5 h-5 text-muted-foreground hover:bg-muted/50 cursor-pointer"
                    @click.stop="data.onDebugSkip?.(props.id)"
                  >
                    <span class="icon-[lucide--skip-forward] w-3.5 h-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  跳过此节点
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </template>
          <!-- 失败节点：从此继续快捷入口 -->
          <TooltipProvider v-if="data.status === 'failed'">
            <Tooltip>
              <TooltipTrigger as-child>
                <button
                  :disabled="!data.canResume"
                  class="inline-flex items-center justify-center rounded-md transition-colors w-5 h-5" :class="[data.canResume ? 'text-primary hover:bg-primary/10 cursor-pointer' : 'text-muted-foreground/40 cursor-not-allowed']"
                  @click.stop="data.canResume && data.onResumeClick?.(props.id)"
                >
                  <span class="icon-[lucide--play-circle] w-3.5 h-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                {{ data.canResume ? '从此继续执行' : '工作流已修改，无法从此继续' }}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <!-- AI 节点成本徽章 + Tooltip -->
          <TooltipProvider v-if="data.cost">
            <Tooltip>
              <TooltipTrigger as-child>
                <Badge
                  variant="secondary"
                  class="text-[10px] h-4 px-1 tabular-nums cursor-default"
                >
                  <span class="icon-[lucide--coins] w-2.5 h-2.5 mr-0.5 text-amber-500" />
                  {{ costText }}
                </Badge>
              </TooltipTrigger>
              <TooltipContent side="bottom" class="max-w-xs">
                <div class="text-xs space-y-1">
                  <div
                    v-for="(modelData, modelName) in data.cost.models"
                    :key="modelName"
                    class="flex items-center justify-between gap-3"
                  >
                    <span class="font-medium truncate">{{ modelName }}</span>
                    <span class="text-muted-foreground tabular-nums whitespace-nowrap">
                      {{ formatTokenCount(modelData.input_tokens) }} in /
                      {{ formatTokenCount(modelData.output_tokens) }} out
                    </span>
                  </div>
                  <div class="border-t border-border/50 pt-1 flex items-center justify-between gap-3 font-medium">
                    <span>总计</span>
                    <span class="tabular-nums">{{ formatTokenCount(data.cost.totalTokens) }} tokens</span>
                  </div>
                </div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <Badge
            v-if="data.isBottleneck"
            variant="outline"
            class="text-[10px] h-4 px-1"
            :class="data.bottleneckLevel === 'critical' ? 'border-red-400/50 text-red-500' : 'border-yellow-400/50 text-yellow-600'"
          >
            {{ data.bottleneckLevel === 'critical' ? '瓶颈 #1' : '瓶颈' }}
          </Badge>
        </div>
      </div>

      <!-- 子步骤展开区域（仅 AI 节点且有进度） -->
      <div v-if="hasSubSteps" class="mt-1.5 pt-1.5 border-t border-border/30">
        <button
          class="flex items-center gap-1.5 w-full text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          @click.stop="toggleExpand"
        >
          <span
            class="icon-[lucide--chevron-right] w-3 h-3 transition-transform duration-200"
            :class="{ 'rotate-90': expanded }"
          />
          <span class="tabular-nums">{{ progressText }}</span>
        </button>

        <!-- 展开的时间线 -->
        <div v-if="expanded" class="overflow-hidden">
          <SubStepTimeline
            :steps="nodeSubSteps"
            @step-click="handleSubStepClick"
          />
        </div>
      </div>
    </div>

    <Handle type="source" :position="Position.Bottom" />
  </div>
</template>

<style scoped>
/* 运行中节点脉冲动画 */
.node-running-border {
  animation: node-pulse 2s ease-in-out infinite;
}

@keyframes node-pulse {
  0%,
  100% {
    border-color: rgba(96, 165, 250, 0.5);
    box-shadow: 0 0 0 0 rgba(96, 165, 250, 0.2);
  }
  50% {
    border-color: rgba(96, 165, 250, 0.8);
    box-shadow: 0 0 8px 2px rgba(96, 165, 250, 0.15);
  }
}

/* 调试暂停节点脉冲动画 */
.node-debug-paused-border {
  animation: node-debug-pulse 1.5s ease-in-out infinite;
}

@keyframes node-debug-pulse {
  0%,
  100% {
    border-color: rgba(245, 158, 11, 0.5);
    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.2);
  }
  50% {
    border-color: rgba(245, 158, 11, 0.9);
    box-shadow: 0 0 12px 3px rgba(245, 158, 11, 0.25);
  }
}
</style>
