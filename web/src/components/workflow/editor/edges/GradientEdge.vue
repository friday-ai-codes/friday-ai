<script setup lang="ts">
/**
 * GradientEdge - 自定义渐变边组件
 *
 * 根据源/目标节点类别色渲染 SVG 线性渐变，选中时加粗发光。
 * 支持 data.flowing 光点流动动画和 data.skipped 灰色虚线样式。
 */
import { BaseEdge, getBezierPath, type EdgeProps } from '@vue-flow/core'
import { computed } from 'vue'
import { getNodeDefinition } from '~/types/workflow/registry'
const props = defineProps<EdgeProps>
const path = computed( => getBezierPath(props))
const CATEGORY_COLORS: Record<string, string> = {
 trigger: '#F59E0B',
 action: '#10B981',
 control: '#64748B',
 integration: '#3B82F6',
 ai: '#8B5CF6',
}
const DEFAULT_COLOR = '#6B7280'
function getColor(nodeType: string | undefined): string {
 if (!nodeType) return DEFAULT_COLOR
 const def = getNodeDefinition(nodeType)
 return CATEGORY_COLORS[def?.category ?? ''] ?? DEFAULT_COLOR
}
const sourceColor = computed( => getColor(props.sourceNode?.data?.nodeType as string))
const targetColor = computed( => getColor(props.targetNode?.data?.nodeType as string))
const gradientId = computed( => `edge-gradient-${props.id}`)
/** 光点流动状态：由外部通过 data.flowing 驱动 */
const isFlowing = computed( => (props.data as Record<string, unknown>)?.flowing === true)
/** 跳过状态：由外部通过 data.skipped 驱动 */
const isSkipped = computed( => (props.data as Record<string, unknown>)?.skipped === true)
/** 光点沿路径流动的周期（秒），4 个光点均匀分布 */
const flowDuration = 2
const edgeStyle = computed( => {
 // skipped 状态：灰色虚线，覆盖渐变
 if (isSkipped.value) {
 return {
 stroke: '#9CA3AF',
 strokeDasharray: '6 4',
 strokeWidth: 1.5,
 filter: 'none',
 transition: 'stroke-width 0.2s, filter 0.2s, stroke 0.3s',
 }
 }
 return {
 stroke: `url(#${gradientId.value})`,
 strokeWidth: isFlowing.value ? 2: (props.selected ? 3: 1.5),
 filter: props.selected ? 'drop-shadow(0 0 4px rgba(139,92,246,0.5))': 'none',
 transition: 'stroke-width 0.2s, filter 0.2s, stroke 0.3s',
 }
})
</script>
<script lang="ts">
export default { inheritAttrs: false }
</script>
<template>
 <defs>
 <linearGradient:id="gradientId"
 gradientUnits="userSpaceOnUse":x1="sourceX":y1="sourceY":x2="targetX":y2="targetY"
 >
 <stop offset="0%":stop-color="sourceColor" />
 <stop offset="100%":stop-color="targetColor" />
 </linearGradient>
 </defs>
 <BaseEdge:id="id":path="path[0]":marker-end="markerEnd":style="edgeStyle" />
 <!-- 隐藏的 path 元素，供 animateMotion mpath 引用 -->
 <path:id="`flow-path-${id}`":d="path[0]"
 fill="none"
 stroke="none"
 />
 <!-- 光点流动动画：4 个蓝色光点沿贝塞尔路径流动 -->
 <template v-if="isFlowing">
 <defs>
 <radialGradient:id="`dot-glow-${id}`">
 <stop offset="0%" stop-color="rgba(59,130,246,0.9)" />
 <stop offset="60%" stop-color="rgba(6,182,212,0.5)" />
 <stop offset="100%" stop-color="rgba(59,130,246,0)" />
 </radialGradient>
 </defs>
 <circle
 v-for="i in 4":key="`dot-${id}-${i}`"
 r="3":fill="`url(#dot-glow-${id})`"
 >
 <animateMotion:dur="`${flowDuration}s`"
 repeatCount="indefinite":begin="`${(i - 1) * (flowDuration / 4)}s`"
 >
 <mpath:href="`#flow-path-${id}`" />
 </animateMotion>
 </circle>
 </template>
</template>
