<script setup lang="ts">
import type { ConnectionLineProps } from '@vue-flow/core'
/**
 * CustomConnectionLine - 拖拽连线组件
 *
 * 照抄 dify custom-connection-line.tsx：拖拽中的连线与连成后的边使用同一种
 * bezier（source=Right→target=Left，curvature 0.16），保证拖拽预览与最终边形状一致。
 */
import { getBezierPath, Position } from '@vue-flow/core'
import { computed } from 'vue'

const props = defineProps<ConnectionLineProps>()

const path = computed(() => {
  const [d] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: Position.Right,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: Position.Left,
    curvature: 0.16,
  })
  return d
})
</script>

<template>
  <g>
    <path
      fill="none"
      stroke="#94a3b8"
      stroke-width="2"
      stroke-dasharray="5 5"
      :d="path"
    />
    <!-- 目标端小竖条，提示落点 -->
    <rect
      :x="targetX"
      :y="targetY - 4"
      width="2"
      height="8"
      fill="#14b8a6"
    />
  </g>
</template>
