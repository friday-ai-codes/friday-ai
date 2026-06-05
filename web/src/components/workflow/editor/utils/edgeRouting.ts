import { getBezierPath, getSmoothStepPath, Position } from '@vue-flow/core'

interface EdgeRouteInput {
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
}

export interface EdgeRouteResult {
  path: string
  labelX: number
  labelY: number
  strategy: 'smooth-step' | 'horizontal-bezier' | 'return-bezier'
}

/**
 * 根据节点相对位置自适应选择更自然的连线路径：
 * - 横向分支优先走侧向 bezier，避免出现笨重的大折返
 * - 逆向/回流边走柔和 bezier，减轻交叉感
 * - 常规自上而下流程仍保持圆角折线，保留流程图语义
 */
export function getWorkflowEdgeRoute({
  sourceX,
  sourceY,
  targetX,
  targetY,
}: EdgeRouteInput): EdgeRouteResult {
  const dx = targetX - sourceX
  const dy = targetY - sourceY
  const absDx = Math.abs(dx)
  const absDy = Math.abs(dy)

  if (absDx > Math.max(140, absDy * 0.85)) {
    const [path, labelX, labelY] = getBezierPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition: dx >= 0 ? Position.Right : Position.Left,
      targetPosition: dx >= 0 ? Position.Left : Position.Right,
      curvature: absDx > 260 ? 0.22 : 0.3,
    })

    return {
      path,
      labelX,
      labelY,
      strategy: 'horizontal-bezier',
    }
  }

  if (dy < -48) {
    const [path, labelX, labelY] = getBezierPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition: Position.Top,
      targetPosition: Position.Bottom,
      curvature: 0.22,
    })

    return {
      path,
      labelX,
      labelY,
      strategy: 'return-bezier',
    }
  }

  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    borderRadius: 22,
    offset: 26,
  })

  return {
    path,
    labelX,
    labelY,
    strategy: 'smooth-step',
  }
}
