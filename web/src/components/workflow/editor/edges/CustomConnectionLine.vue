<script setup lang="ts">
import type { ConnectionLineProps } from '@vue-flow/core'
/**
 * CustomConnectionLine - 拖拽连线组件
 *
 * 照抄 dify custom-connection-line.tsx：拖拽中的连线与连成后的边使用同一种
 * bezier（source=Right→target=Left，curvature 0.16），保证拖拽预览与最终边形状一致。
 *
 * SLOT-03 磁吸：可选 `snapX/snapY`（flow 坐标）由 WorkflowCanvas 经 `#connection-line`
 * slot 透传——命中吸附时用吸附端点替代 targetX/Y 绘制 bezier 终点，并把"落点小竖条"
 * 升级为更醒目的 snap-locked 标记（emerald 实心圆 + 脉冲环，遵循 prefers-reduced-motion
 * 既有全局降级，本组件再叠一层 media query 兜底）。
 */
import { getBezierPath, Position } from '@vue-flow/core'
import { computed } from 'vue'

const props = defineProps<ConnectionLineProps & {
  /** 吸附命中时的目标端点 X（flow 坐标）；未命中为 undefined（用原始 targetX）。 */
  snapX?: number
  /** 吸附命中时的目标端点 Y（flow 坐标）；未命中为 undefined（用原始 targetY）。 */
  snapY?: number
}>()

/** 是否命中吸附（snap-locked 态）。 */
const snapped = computed(() => props.snapX != null && props.snapY != null)

/** 终点坐标：命中吸附用吸附端点，否则用 Vue Flow 提供的 targetX/Y。 */
const endX = computed(() => props.snapX ?? props.targetX)
const endY = computed(() => props.snapY ?? props.targetY)

const path = computed(() => {
  const [d] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: Position.Right,
    targetX: endX.value,
    targetY: endY.value,
    targetPosition: Position.Left,
    curvature: 0.16,
  })
  return d
})
</script>

<template>
  <g :class="{ 'snap-locked': snapped }">
    <path
      fill="none"
      :stroke="snapped ? '#10b981' : '#94a3b8'"
      stroke-width="2"
      stroke-dasharray="5 5"
      :d="path"
    />
    <!-- 命中吸附：emerald 实心圆 + 脉冲环（snap-locked）；未命中：落点小竖条 -->
    <template v-if="snapped">
      <circle
        class="snap-pulse"
        :cx="endX"
        :cy="endY"
        r="6"
        fill="none"
        stroke="#10b981"
        stroke-width="2"
      />
      <circle
        :cx="endX"
        :cy="endY"
        r="3"
        fill="#10b981"
      />
    </template>
    <rect
      v-else
      :x="endX"
      :y="endY - 4"
      width="2"
      height="8"
      fill="#14b8a6"
    />
  </g>
</template>

<style scoped>
.snap-pulse {
  transform-box: fill-box;
  transform-origin: center;
  animation: snap-pulse 1s ease-out infinite;
}

@keyframes snap-pulse {
  0% {
    opacity: 0.9;
    transform: scale(0.7);
  }
  100% {
    opacity: 0;
    transform: scale(1.8);
  }
}

@media (prefers-reduced-motion: reduce) {
  .snap-pulse {
    animation: none;
  }
}
</style>
