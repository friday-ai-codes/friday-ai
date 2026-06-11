/**
 * Galaxy 确定性同心环布局（借鉴 GitNexus circles-layout 思路）
 *
 * 核心目标：节点不从随机位置开始力导向模拟，而是先按"类型分环 + 仓库/目录分扇区"
 * 计算出接近终态的初始坐标 —— 首屏即成型，避免用户看到布局抖动收敛的过程。
 *
 * 布局规则：
 * - 环（半径）按节点类型分配：endpoint / api_wrapper 在内环（API 核心面），
 *   symbol 在中环，chunk_registry 在外环，api_call_site 在最外环。
 * - 角度按 (仓库 → 顶级目录 → 文件路径) 的全局排序分配：同一文件的不同类型节点
 *   角度相近 → 跨环径向对齐，目录形成天然的角度聚类。
 * - 确定性 hash 抖动：同样的数据集每次刷新得到同样的布局。
 *
 * 之后 ForceAtlas2（Web Worker）在这些初始位置上做短时精修即可收敛。
 */

export interface CirclesLayoutNode {
  id: string
  type: string
  label: string
  repository_id?: string
  file_path?: string
}

export interface CirclesNodePosition {
  x: number
  y: number
  /** 逻辑环序号：0 = 最内环 */
  ring: number
  /** 弧度制角度，供后续物理模拟做锚点参考 */
  angle: number
}

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

/** 每个环的目标半径（px，sigma 逻辑坐标） */
export const CIRCLES_RING_RADII = [110, 260, 430, 620] as const

export const RING_COUNT = CIRCLES_RING_RADII.length

/** 节点类型 → 环序号 */
const TYPE_TO_RING: Record<string, number> = {
  // 内环：API 表面（系统对外能力的核心）
  endpoint: 0,
  api_wrapper: 0,
  // 中环：符号（函数/类等代码结构）
  symbol: 1,
  // 外环：代码 chunk（数量最多）
  chunk_registry: 2,
  // 最外环：API 调用点
  api_call_site: 3,
}

const DEFAULT_RING = 2

/** L2 总览模式下仓库节点的排布半径 */
const REPO_RING_RADIUS = 300

/** 径向抖动幅度（±px），避免同环节点完全共圆显得呆板 */
const RADIAL_JITTER = 18

// ---------------------------------------------------------------------------
// 内部工具
// ---------------------------------------------------------------------------

/** djb2 确定性 hash → [0, 1) */
export function deterministicHash(str: string): number {
  let hash = 5381
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) + hash + str.charCodeAt(i)
    hash |= 0
  }
  return (Math.abs(hash) % 10000) / 10000
}

function topLevelDir(filePath: string): string {
  const idx = filePath.indexOf('/')
  return idx === -1 ? '' : filePath.slice(0, idx)
}

/** 排序 key：仓库 → 顶级目录 → 完整路径 → id（保证完全确定性） */
function sortKey(node: CirclesLayoutNode): string {
  const repo = node.repository_id ?? ''
  const path = node.file_path ?? ''
  return `${repo}\u0000${topLevelDir(path)}\u0000${path}\u0000${node.id}`
}

// ---------------------------------------------------------------------------
// 公开 API
// ---------------------------------------------------------------------------

/**
 * L1 细粒度图布局：类型分环 + 仓库/目录全局角度排序。
 */
export function calculateCirclesLayout(
  nodes: CirclesLayoutNode[],
): Map<string, CirclesNodePosition> {
  const positions = new Map<string, CirclesNodePosition>()
  if (nodes.length === 0)
    return positions

  // 仓库总览（L2）：仓库节点单环均匀排布
  if (nodes.every(n => n.type === 'repository'))
    return calculateRepoRingLayout(nodes)

  const TWO_PI = Math.PI * 2
  const sorted = [...nodes].sort((a, b) => sortKey(a).localeCompare(sortKey(b)))
  const total = sorted.length

  for (let i = 0; i < total; i++) {
    const node = sorted[i]
    const ring = TYPE_TO_RING[node.type] ?? DEFAULT_RING

    // 全局序号决定角度：同文件/同目录节点角度相邻，跨环径向对齐
    const baseAngle = (i / total) * TWO_PI
    // 确定性角度微抖动（不超过半个槽位），缓解同文件节点初始重叠
    const slot = TWO_PI / total
    const angle = baseAngle + (deterministicHash(`${node.id}:a`) - 0.5) * slot

    const radius
      = CIRCLES_RING_RADII[ring]
        + (deterministicHash(`${node.id}:r`) - 0.5) * 2 * RADIAL_JITTER

    positions.set(node.id, {
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
      ring,
      angle,
    })
  }

  return positions
}

/**
 * L2 总览布局：仓库节点按 label 排序后均匀分布在单环上。
 */
function calculateRepoRingLayout(
  nodes: CirclesLayoutNode[],
): Map<string, CirclesNodePosition> {
  const positions = new Map<string, CirclesNodePosition>()
  const TWO_PI = Math.PI * 2
  const sorted = [...nodes].sort((a, b) =>
    `${a.label}\u0000${a.id}`.localeCompare(`${b.label}\u0000${b.id}`),
  )

  // 节点数多时适当扩大半径，保持节点间距
  const radius = sorted.length <= 1
    ? 0
    : Math.max(REPO_RING_RADIUS, sorted.length * 28)

  for (let i = 0; i < sorted.length; i++) {
    const angle = (i / sorted.length) * TWO_PI
    positions.set(sorted[i].id, {
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
      ring: 0,
      angle,
    })
  }

  return positions
}
