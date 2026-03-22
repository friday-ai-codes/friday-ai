<script setup lang="ts">
import type { EdgeProps } from '@vue-flow/core'
/**
 * GradientEdge - 自定义渐变边组件
 *
 * 根据源/目标节点类别色渲染 SVG 线性渐变，选中时加粗发光。
 */
import { BaseEdge, getSmoothStepPath } from '@vue-flow/core'
import { computed } from 'vue'
import { getNodeDefinition } from '~/types/workflow/registry'
const props = defineProps<EdgeProps>
const path = computed( => getSmoothStepPath(props))
const CATEGORY_COLORS: Record<string, string> = {
 trigger: '#F59E0B',
 action: '#10B981',
 control: '#64748B',
 integration: '#3B82F6',
 ai: '#8B5CF6',
}
const DEFAULT_COLOR = '#6B7280'
function getColor(nodeType: string | undefined): string {
 if (!nodeType)
 return DEFAULT_COLOR
 const def = getNodeDefinition(nodeType)
 return CATEGORY_COLORS[def?.category ?? ''] ?? DEFAULT_COLOR
}
const sourceColor = computed( => getColor(props.sourceNode?.data?.nodeType as string))
const targetColor = computed( => getColor(props.targetNode?.data?.nodeType as string))
const gradientId = computed( => `edge-gradient-${props.id}`)
const edgeStyle = computed( => ({
 stroke: `url(#${gradientId.value})`,
 strokeWidth: props.selected ? 3: 1.5,
 filter: props.selected ? 'drop-shadow(0 0 4px rgba(139,92,246,0.5))': 'none',
 transition: 'stroke-width 0.2s, filter 0.2s',
}))
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
</template>
