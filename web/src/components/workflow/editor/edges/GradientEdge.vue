<script setup lang="ts">
import type { EdgeProps } from '@vue-flow/core'
/**
 * GradientEdge - 自定义渐变边组件
 *
 * 根据源/目标节点类别色渲染 SVG 线性渐变，选中时加粗发光。
 * 支持 label 显示（如审批驳回的「驳回修改」标签）。
 */
import { BaseEdge } from '@vue-flow/core'
import { computed } from 'vue'
import { getNodeDefinition } from '~/types/workflow/registry'
import { getWorkflowEdgeRoute } from '../utils/edgeRouting'

const props = defineProps<EdgeProps>()

const route = computed(() => getWorkflowEdgeRoute({
  sourceX: props.sourceX,
  sourceY: props.sourceY,
  targetX: props.targetX,
  targetY: props.targetY,
}))

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

const sourceColor = computed(() => getColor(props.sourceNode?.data?.nodeType as string))
const targetColor = computed(() => getColor(props.targetNode?.data?.nodeType as string))
const gradientId = computed(() => `edge-gradient-${props.id}`)

const edgeStyle = computed(() => ({
  stroke: `url(#${gradientId.value})`,
  strokeWidth: props.selected ? 2.5 : 2,
  strokeOpacity: props.selected ? 0.95 : 0.82,
  filter: props.selected ? 'drop-shadow(0 0 6px rgba(139,92,246,0.45))' : 'drop-shadow(0 1px 2px rgba(15,23,42,0.08))',
  transition: 'stroke-width 0.2s, stroke-opacity 0.2s, filter 0.2s',
  ...(props.animated
    ? {
        strokeDasharray: '5 5',
        animation: 'gradient-edge-dash-flow 0.5s linear infinite',
      }
    : {}),
}))
</script>

<script lang="ts">
export default { inheritAttrs: false }
</script>

<template>
  <defs>
    <linearGradient
      :id="gradientId"
      gradientUnits="userSpaceOnUse"
      :x1="sourceX"
      :y1="sourceY"
      :x2="targetX"
      :y2="targetY"
    >
      <stop offset="0%" :stop-color="sourceColor" />
      <stop offset="100%" :stop-color="targetColor" />
    </linearGradient>
  </defs>
  <BaseEdge
    :id="id"
    :path="route.path"
    :label="label"
    :label-x="route.labelX"
    :label-y="route.labelY"
    :label-style="{ fill: 'hsl(var(--foreground))', fontSize: '11px', fontWeight: 600 }"
    :label-bg-style="{ fill: 'hsl(var(--card))', fillOpacity: 0.94, stroke: 'rgba(148, 163, 184, 0.22)', strokeWidth: 1 }"
    :label-bg-padding="[4, 9]"
    :label-bg-border-radius="999"
    :marker-end="markerEnd"
    :style="edgeStyle"
  />
</template>

<style>
/* 全局 keyframes — BaseEdge 渲染的 path 不在本组件 scoped DOM 内 */
@keyframes gradient-edge-dash-flow {
  from {
    stroke-dashoffset: 0;
  }
  to {
    stroke-dashoffset: -10;
  }
}
</style>
