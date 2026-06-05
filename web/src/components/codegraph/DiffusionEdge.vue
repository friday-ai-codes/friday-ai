<script setup lang="ts">
/**
 * GraphRAG 二跳扩散自定义边（ 骨架 + tooltip 实装，UI-SPEC / ）
 *
 * 接收 Vue Flow EdgeProps；stroke / strokeWidth / strokeDasharray / opacity
 * 全部从 :style 注入（来自 useDiffusionGraph composable），模板零硬编码颜色
 * （UI-SPEC §10 硬约束 3）。
 *
 * 边 hover tooltip（ 完整落地）：EdgeLabelRenderer 内 hit-area 包 TooltipProvider →
 * TooltipContent 显示 edge_type chip（inline hex+alpha 15%）+ weight 2 位小数 + reason 文本。
 * Deviation D-A：UI-SPEC §10 硬约束 12 字面要求 `bg-{color}-500/15 text-{color}-700` Tailwind
 * 模式，本 plan 选 inline style hex+alpha 等价实现，保持颜色单一真值源
 * （DIFFUSION_EDGE_COLORS）与 BaseEdge stroke 一致。
 */
import type { Position } from '@vue-flow/core'
import type { EdgeType } from '~/lib/diffusionEdgeColors'
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from '@vue-flow/core'
import { computed } from 'vue'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { DIFFUSION_EDGE_COLORS } from '~/lib/diffusionEdgeColors'

const props = defineProps<{
  id: string
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  sourcePosition: Position
  targetPosition: Position
  style?: Record<string, unknown>
  markerEnd?: string
  data?: { edgeType: string, weight: number, reason: string, hop: 1 | 2 }
}>()

const pathInfo = computed(() => getSmoothStepPath({
  sourceX: props.sourceX,
  sourceY: props.sourceY,
  sourcePosition: props.sourcePosition,
  targetX: props.targetX,
  targetY: props.targetY,
  targetPosition: props.targetPosition,
}))

const pathD = computed(() => pathInfo.value[0])
const labelX = computed(() => pathInfo.value[1])
const labelY = computed(() => pathInfo.value[2])

const labelTransform = computed(
  () => `translate(-50%, -50%) translate(${labelX.value}px, ${labelY.value}px)`,
)

// chip 颜色：从 DIFFUSION_EDGE_COLORS 取，未知 edgeType 用灰色兜底，
// 等价于 UI-SPEC §10 硬约束 12 的 bg-{color}-500/15 视觉对比度
const chipColor = computed<string>(() => {
  const t = props.data?.edgeType
  if (typeof t !== 'string')
    return '#6b7280'
  return DIFFUSION_EDGE_COLORS[t as EdgeType] ?? '#6b7280'
})

// hex + alpha (0x26 ≈ 15%) — 与 UI-SPEC 的 bg-…/15 视觉同等
const chipBg = computed(() => `${chipColor.value}26`)

const reasonText = computed(() => {
  const r = props.data?.reason
  if (typeof r !== 'string' || r.length === 0)
    return '（无说明）'
  return r
})

const weightText = computed(() => {
  const w = props.data?.weight
  if (typeof w !== 'number' || Number.isNaN(w))
    return 'weight ?'
  return `weight ${w.toFixed(2)}`
})
</script>

<template>
  <BaseEdge :id="id" :path="pathD" :marker-end="markerEnd" :style="style" />
  <EdgeLabelRenderer>
    <div
      class="absolute pointer-events-auto"
      :style="{ transform: labelTransform }"
    >
      <!-- HI-07：TooltipProvider 提到 GraphRAGDiffusionTab 单实例 -->
      <Tooltip>
        <TooltipTrigger as-child>
          <!-- HI-02: 增大热区（w-5 h-5）+ tabindex + focus-visible 视觉提示 -->
          <div
            class="w-5 h-5 rounded-full bg-transparent focus-visible:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring cursor-help"
            tabindex="0"
            :aria-label="`${data?.edgeType ?? 'edge'} ${weightText}`"
          />
        </TooltipTrigger>
        <TooltipContent class="max-w-[320px]">
          <div class="flex items-center gap-2 mb-1.5">
            <!-- ME-04: chip 颜色经 CSS 变量 + Tailwind arbitrary value，
                 className 表达样式意图，仅 :style 注入变量值（D-A 备案视觉等价） -->
            <span
              class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--chip-bg)] text-[var(--chip-color)]"
              :style="({ '--chip-bg': chipBg, '--chip-color': chipColor }) as Record<string, string>"
            >{{ data?.edgeType }}</span>
            <span class="text-xs font-mono tabular-nums text-muted-foreground">
              {{ weightText }}
            </span>
          </div>
          <p class="text-sm">
            {{ reasonText }}
          </p>
        </TooltipContent>
      </Tooltip>
    </div>
  </EdgeLabelRenderer>
</template>
