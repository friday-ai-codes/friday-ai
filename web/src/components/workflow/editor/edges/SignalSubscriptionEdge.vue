<script setup lang="ts">
import type { EdgeProps } from '@vue-flow/core'
import type { SignalSubscriptionEdgeData } from '../composables/useSignalLayer'
/**
 * SignalSubscriptionEdge —— P6 信号订阅边（虚线 + 信号语义色）。
 *
 * 与实线 gradient 交付边视觉强区分：单色虚线（data.color 来自 SIGNAL_META，成功绿/失败红/
 * 产出紫）+ 流动动画 + 中点信号小标签（成功/失败/产出）。纯渲染叠加，不参与连线/插入交互。
 */
import { BaseEdge, EdgeLabelRenderer, getBezierPath, Position } from '@vue-flow/core'
import { computed } from 'vue'

const props = defineProps<EdgeProps<SignalSubscriptionEdgeData>>()

const color = computed(() => props.data?.color ?? '#8b5cf6')
const label = computed(() => props.data?.label ?? '')

const route = computed(() => {
  const [path, labelX, labelY] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition ?? Position.Right,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition ?? Position.Left,
    curvature: 0.16,
  })
  return { path, labelX, labelY }
})

const edgeStyle = computed(() => ({
  stroke: color.value,
  strokeWidth: 1.5,
  strokeOpacity: 0.9,
  strokeDasharray: '6 4',
  animation: 'signal-edge-dash-flow 0.6s linear infinite',
}))
</script>

<script lang="ts">
export default { inheritAttrs: false }
</script>

<template>
  <BaseEdge
    :id="id"
    :path="route.path"
    :style="edgeStyle"
  />
  <!-- 中点信号小标签：信号语义色描边 pill（成功/失败/产出） -->
  <EdgeLabelRenderer>
    <div
      v-if="label"
      class="nopan nodrag signal-edge-pill"
      :style="{
        position: 'absolute',
        transform: `translate(-50%, -50%) translate(${route.labelX}px, ${route.labelY}px)`,
        color,
        borderColor: color,
      }"
    >
      {{ label }}
    </div>
  </EdgeLabelRenderer>
</template>

<style scoped>
.signal-edge-pill {
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid currentColor;
  background: hsl(var(--card));
  pointer-events: none;
  white-space: nowrap;
}
</style>

<style>
/* 全局 keyframes —— BaseEdge 渲染的 path 不在本组件 scoped DOM 内 */
@keyframes signal-edge-dash-flow {
  from {
    stroke-dashoffset: 0;
  }
  to {
    stroke-dashoffset: -10;
  }
}
</style>
