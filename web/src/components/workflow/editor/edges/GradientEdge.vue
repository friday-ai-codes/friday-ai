<script setup lang="ts">
import type { EdgeProps } from '@vue-flow/core'
/**
 * GradientEdge - 自定义渐变边组件
 *
 * 根据源/目标节点类别色渲染 SVG 线性渐变，选中时加粗发光。
 * 支持 label 显示（如审批驳回的「驳回修改」标签）。
 */
import { BaseEdge, EdgeLabelRenderer } from '@vue-flow/core'
import { computed, ref } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateShortId } from '~/utils/shortId'
import { randomUUID } from '~/utils/uuid'
import NodeInsertMenu from '../NodeInsertMenu.vue'
import { getWorkflowEdgeRoute } from '../utils/edgeRouting'

const props = defineProps<EdgeProps>()

const store = useWorkflowsStore()

/** 悬停连线时浮出中点 "+"（mouseenter/mouseleave 控制透明度与 pointer-events） */
const hovering = ref(false)

/**
 * 在该边中点插入新节点：删旧边 + 新节点 + 两条新边。
 * 照抄 dify custom-edge.tsx handleInsert 的「断开-插入-重连」语义。
 */
function onInsert(nodeType: string) {
  const def = getNodeDefinition(nodeType)
  const sourcePos = props.sourceNode?.position ?? { x: props.sourceX, y: props.sourceY }
  const targetPos = props.targetNode?.position ?? { x: props.targetX, y: props.targetY }
  const newNodeId = randomUUID()

  store.removeEdge(props.id)
  store.addNode({
    id: newNodeId,
    shortId: generateShortId(),
    nodeType,
    name: def?.displayName || nodeType,
    description: '',
    position: {
      x: (sourcePos.x + targetPos.x) / 2,
      y: (sourcePos.y + targetPos.y) / 2,
    },
    config: (def?.defaultConfig as Record<string, unknown>) ?? {},
    onError: 'abort',
    retryTimes: 0,
    retryDelay: 5,
    nodeTimeoutSeconds: null,
    fallbackValues: null,
    runCondition: null,
    metadata: {},
  })
  store.addEdge({
    id: `edge-${props.source}-${newNodeId}-${Date.now()}`,
    source: props.source,
    target: newNodeId,
    sourcePort: props.sourceHandleId ?? 'default',
    targetPort: 'default',
    label: undefined,
    condition: null,
  })
  store.addEdge({
    id: `edge-${newNodeId}-${props.target}-${Date.now()}`,
    source: newNodeId,
    target: props.target,
    sourcePort: 'default',
    targetPort: props.targetHandleId ?? 'default',
    label: undefined,
    condition: null,
  })
}

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
  <!-- 透明加宽命中路径：驱动连线悬停态，使中点 "+" 浮现 -->
  <path
    :d="route.path"
    fill="none"
    stroke="transparent"
    :stroke-width="20"
    style="pointer-events: stroke;"
    @mouseenter="hovering = true"
    @mouseleave="hovering = false"
  />
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
  <!-- 边中点悬停浮出 "+"：点击选节点后在该边中间插入新节点 -->
  <EdgeLabelRenderer>
    <div
      class="nopan nodrag"
      :style="{
        position: 'absolute',
        transform: `translate(-50%, -50%) translate(${route.labelX}px, ${route.labelY}px)`,
        pointerEvents: hovering ? 'all' : 'none',
        opacity: hovering ? 1 : 0,
        transition: 'opacity 0.15s',
      }"
      @mouseenter="hovering = true"
      @mouseleave="hovering = false"
    >
      <NodeInsertMenu @select="onInsert" />
    </div>
  </EdgeLabelRenderer>
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
