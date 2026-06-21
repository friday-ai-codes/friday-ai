import { getBezierPath, Position } from '@vue-flow/core'

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
}

/**
 * 单一连线路径：照抄 dify custom-edge.tsx 的铁律。
 *
 * Handle 永远 source=Right / target=Left，连线只有一种 curvature 0.16 的 bezier。
 * 这是消灭"连线飘"的命门——连线方向（横向 L→R）与 Handle 方向必须一致，
 * 不再按节点相对位置切换 smooth-step / 折返 bezier，避免方向自相矛盾。
 *
 * sourceX 减 8 / targetX 加 8 让连线在 Handle 处留出微小内缩，与 dify 视觉一致。
 */
export function getWorkflowEdgeRoute({
  sourceX,
  sourceY,
  targetX,
  targetY,
}: EdgeRouteInput): EdgeRouteResult {
  const [path, labelX, labelY] = getBezierPath({
    sourceX: sourceX - 8,
    sourceY,
    sourcePosition: Position.Right,
    targetX: targetX + 8,
    targetY,
    targetPosition: Position.Left,
    curvature: 0.16,
  })

  return { path, labelX, labelY }
}
