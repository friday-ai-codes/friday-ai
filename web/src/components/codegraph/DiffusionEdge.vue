<script setup lang="ts">
/**
 * GraphRAG 二跳扩散自定义边（Phase Plan，work item §5.4）
 *
 * 接收 Vue Flow EdgeProps；stroke / strokeWidth / strokeDasharray / opacity
 * 全部从:style 注入（来自 useDiffusionGraph composable），模板零硬编码颜色
 * （work item §10 硬约束 3）。本 plan 留 EdgeLabelRenderer hit-area 占位锚点，
 * 边 hover tooltip 内容由 Plan 接力扩展。
 */
import type { Position } from '@vue-flow/core'
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from '@vue-flow/core'
import { computed } from 'vue'
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
}>
const pathInfo = computed( => getSmoothStepPath({
 sourceX: props.sourceX,
 sourceY: props.sourceY,
 sourcePosition: props.sourcePosition,
 targetX: props.targetX,
 targetY: props.targetY,
 targetPosition: props.targetPosition,
}))
const pathD = computed( => pathInfo.value[0])
const labelX = computed( => pathInfo.value[1])
const labelY = computed( => pathInfo.value[2])
const labelTransform = computed(
 => `translate(-50%, -50%) translate(${labelX.value}px, ${labelY.value}px)`,
)
</script>
<template>
 <BaseEdge:id="id":path="pathD":marker-end="markerEnd":style="style" />
 <EdgeLabelRenderer>
 <div
 class="absolute pointer-events-auto":style="{ transform: labelTransform }"
 >
 <!-- Plan 落 edge hover tooltip：包 TooltipProvider + TooltipContent
 显示 edge_type chip + weight + reason；本 plan 仅留隐形 hit-area 锚点 -->
 <div class="w-3 rounded-full opacity-0":aria-hidden="true" />
 </div>
 </EdgeLabelRenderer>
</template>
