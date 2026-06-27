/**
 * 端口吸附几何（SLOT-03 磁吸 snap-locked 态计算核心）。
 *
 * 职责：在拖拽连线时，于"形状兼容的目标 input handle"中找吸附半径内最近者，
 * 返回其中心作连接线视觉吸附端点（flow 坐标）。
 *
 * 关键边界：
 * - 端口吸附阈值 `PORT_SNAP_THRESHOLD = 28px` 是**独立常量**，与
 *   `useAlignmentGuides` 的节点对齐阈值 `SNAP_THRESHOLD = 5` 互不相干——
 *   两套逻辑分离，本模块**绝不**改动节点对齐阈值（零回归命门）。
 * - 阈值为屏幕像素，按 `viewport.zoom` 换算到 flow 坐标后比距，
 *   保证不同缩放下手感一致（屏幕 28px ⇒ flow 距离 28/zoom）。
 * - 候选的 `compatible` 由调用方（93-06）用
 *   `useConnectionDragState.isCompatibleTarget` 预先标注；本函数只比几何、
 *   不查 store，保持纯函数可单测。
 *
 * 合法性：吸附**只改拖拽连接线的视觉端点**，不放行非法连接——最终落点仍由
 * `isValidConnection` + `getValidationError` 双重校验（吸附不绕过合法性）。
 */

/**
 * 端口吸附阈值（屏幕像素），与既有 "+" 追加菜单热区 `-7`（28px）对齐。
 * 独立于 `useAlignmentGuides.SNAP_THRESHOLD=5`，不得混用。
 */
export const PORT_SNAP_THRESHOLD = 28

/** flow 坐标点。 */
export interface SnapPoint {
  x: number
  y: number
}

/** 吸附候选 handle：坐标为 flow 坐标，`compatible` 由调用方预标注。 */
export interface SnapCandidate {
  nodeId: string
  handleId: string
  x: number
  y: number
  compatible: boolean
}

/** 吸附命中结果：目标 handle 标识 + 其中心 flow 坐标（作连接线视觉端点）。 */
export interface SnapTarget {
  nodeId: string
  handleId: string
  x: number
  y: number
}

/**
 * 在兼容候选 handle 中找吸附半径内最近者。
 *
 * @param pointer 当前指针位置（flow 坐标）
 * @param candidates 候选 handle 列表（flow 坐标 + 兼容标注）
 * @param zoom 当前 viewport 缩放（屏幕 28px ⇒ flow 距离 28/zoom）
 * @returns 命中则返回最近兼容 handle 的中心端点；无命中返回 null
 *
 * 规则：
 * - 仅在 `compatible === true` 的候选中比距（不兼容即便在半径内也跳过）。
 * - 欧氏距离 ≤ `PORT_SNAP_THRESHOLD / zoom` 视为命中；多个命中取最近。
 * - 非法 zoom（≤0/非有限）回退按屏幕阈值比距（zoom=1 口径），避免除零。
 */
export function findSnapTarget(
  pointer: SnapPoint,
  candidates: SnapCandidate[],
  zoom: number,
): SnapTarget | null {
  // zoom 防御：非有限或 ≤0 时退回 1（按屏幕阈值比，不放大不缩小），杜绝除零/NaN。
  const safeZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1
  // 屏幕阈值换算到 flow 距离：屏幕越放大（zoom 大）允许的 flow 距离越小。
  const flowThreshold = PORT_SNAP_THRESHOLD / safeZoom

  let best: SnapTarget | null = null
  let bestDist = Number.POSITIVE_INFINITY

  for (const c of candidates) {
    if (!c.compatible)
      continue
    const dx = c.x - pointer.x
    const dy = c.y - pointer.y
    const dist = Math.hypot(dx, dy)
    if (dist <= flowThreshold && dist < bestDist) {
      bestDist = dist
      best = { nodeId: c.nodeId, handleId: c.handleId, x: c.x, y: c.y }
    }
  }

  return best
}
