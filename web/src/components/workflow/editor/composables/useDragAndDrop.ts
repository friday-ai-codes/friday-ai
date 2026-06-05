import type { GraphEdge } from '@vue-flow/core'
import { useVueFlow } from '@vue-flow/core'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { getNodeDefinition } from '~/types/workflow/registry'
import { generateShortId } from '~/utils/shortId'

const RECENT_NODES_KEY = 'friday-recent-nodes'
const MAX_RECENT = 10

/**
 * 记录最近使用的节点类型到 localStorage
 */
function recordRecentNode(nodeType: string): void {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_NODES_KEY) ?? '[]')
    const stored = Array.isArray(parsed) && parsed.every(t => typeof t === 'string') ? parsed : []
    const filtered = stored.filter((t: string) => t !== nodeType)
    filtered.unshift(nodeType)
    localStorage.setItem(RECENT_NODES_KEY, JSON.stringify(filtered.slice(0, MAX_RECENT)))
    // 触发自定义事件通知 NodePalette 刷新
    window.dispatchEvent(new CustomEvent('friday:recent-nodes-changed'))
  }
  catch { /* localStorage 不可用时静默失败 */ }
}

/**
 * 获取最近使用的节点类型列表
 */
export function getRecentNodes(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_NODES_KEY) ?? '[]')
    return Array.isArray(parsed) && parsed.every(t => typeof t === 'string') ? parsed : []
  }
  catch { return [] }
}

/**
 * 计算点到线段的最短距离
 *
 * @param px - 点 x 坐标
 * @param py - 点 y 坐标
 * @param x1 - 线段起点 x
 * @param y1 - 线段起点 y
 * @param x2 - 线段终点 x
 * @param y2 - 线段终点 y
 * @returns 最短距离（像素）
 */
function pointToLineDistance(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy

  if (lenSq === 0) {
    // 线段退化为点
    return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
  }

  // 计算投影参数 t，限制在 [0, 1] 区间内（线段上最近点）
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))

  const closestX = x1 + t * dx
  const closestY = y1 + t * dy

  return Math.sqrt((px - closestX) ** 2 + (py - closestY) ** 2)
}

/** 命中容差：点到 edge 距离小于此值认为落在连线上（px） */
const EDGE_HIT_TOLERANCE = 20

/**
 * 侧边栏拖放到画布的 composable
 *
 * 画布端：监听 dragover/drop 事件，将侧边栏拖来的节点添加到 store。
 * 扩展：检测拖拽节点到已有连线上时自动断开并插入新节点。
 */
export function useDragAndDrop() {
  const { screenToFlowCoordinate, getEdges } = useVueFlow()
  const store = useWorkflowsStore()

  function onDragOver(event: DragEvent) {
    event.preventDefault()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'move'
    }
  }

  function onDrop(event: DragEvent) {
    const nodeType = event.dataTransfer?.getData('application/vueflow')
    if (!nodeType)
      return

    const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
    const def = getNodeDefinition(nodeType)
    const dragName = event.dataTransfer?.getData('application/vueflow-name')

    // 检测是否落在某条 edge 上
    const edges = getEdges.value as GraphEdge[]
    let hitEdge: GraphEdge | null = null
    let minDistance = Infinity

    for (const edge of edges) {
      // 跳过没有坐标的 edge（理论上不会发生）
      if (edge.sourceX == null || edge.sourceY == null || edge.targetX == null || edge.targetY == null)
        continue

      const dist = pointToLineDistance(
        position.x,
        position.y,
        edge.sourceX,
        edge.sourceY,
        edge.targetX,
        edge.targetY,
      )

      if (dist < EDGE_HIT_TOLERANCE && dist < minDistance) {
        minDistance = dist
        hitEdge = edge
      }
    }

    if (hitEdge) {
      // 插入到连线中间：删除原 edge，创建新节点，建立两条新 edge
      const newNodeId = crypto.randomUUID()

      // 创建新节点（放在 drop 位置，稍偏移使中心对准鼠标）
      const newNode = {
        id: newNodeId,
        shortId: generateShortId(),
        nodeType,
        name: dragName || def?.displayName || nodeType,
        description: '',
        position,
        config: def ? (def.schema.parse({}) as Record<string, unknown>) : {},
        onError: 'abort' as const,
        retryTimes: 0,
        retryDelay: 5,
        nodeTimeoutSeconds: null,
        fallbackValues: null,
        runCondition: null,
        metadata: {},
      }
      store.addNode(newNode)

      // 删除原 edge
      store.removeEdge(hitEdge.id)

      // 创建 source → newNode edge
      store.addEdge({
        id: `edge-${hitEdge.source}-${newNodeId}`,
        source: hitEdge.source,
        target: newNodeId,
        sourcePort: hitEdge.sourceHandle ?? 'default',
        targetPort: 'default',
        label: undefined,
        condition: null,
      })

      // 创建 newNode → target edge
      store.addEdge({
        id: `edge-${newNodeId}-${hitEdge.target}`,
        source: newNodeId,
        target: hitEdge.target,
        sourcePort: 'default',
        targetPort: hitEdge.targetHandle ?? 'default',
        label: undefined,
        condition: null,
      })

      recordRecentNode(nodeType)
      return
    }

    // 未命中 edge：走原有逻辑，直接添加节点
    store.addNode({
      id: crypto.randomUUID(),
      shortId: generateShortId(),
      nodeType,
      name: dragName || def?.displayName || nodeType,
      description: '',
      position,
      config: def ? (def.schema.parse({}) as Record<string, unknown>) : {},
      onError: 'abort',
      retryTimes: 0,
      retryDelay: 5,
      nodeTimeoutSeconds: null,
      fallbackValues: null,
      runCondition: null,
      metadata: {},
    })

    recordRecentNode(nodeType)
  }

  return { onDragOver, onDrop }
}
