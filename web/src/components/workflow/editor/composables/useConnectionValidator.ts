import type { Connection } from '@vue-flow/core'
import { useVueFlow } from '@vue-flow/core'

/**
 * 连线验证失败原因（用于 Toast 提示）
 */
export function getValidationError(connection: Connection): string | null {
  const { getEdges } = useVueFlow()

  // 防自连接
  if (connection.source === connection.target) {
    return '不能连接到自身'
  }

  const edges = getEdges.value

  // 防重复连线：按四元组（source/sourceHandle/target/targetHandle）比对，
  // handle 可能为 null，统一 ?? 'default' 归一后再比；
  // 修复「同两节点不同分支端口的多条边被误报重复」。
  const duplicate = edges.some(
    e => e.source === connection.source
      && e.target === connection.target
      && (e.sourceHandle ?? 'default') === (connection.sourceHandle ?? 'default')
      && (e.targetHandle ?? 'default') === (connection.targetHandle ?? 'default'),
  )
  if (duplicate) {
    return '已存在连接'
  }

  // 防环：从 target 出发 BFS，看能否到达 source
  const adjacency = new Map<string, string[]>()
  for (const edge of edges) {
    if (!adjacency.has(edge.source))
      adjacency.set(edge.source, [])
    adjacency.get(edge.source)!.push(edge.target)
  }

  const visited = new Set<string>()
  const queue = [connection.target]
  while (queue.length > 0) {
    const current = queue.shift()!
    if (current === connection.source)
      return '会形成环路'
    if (visited.has(current))
      continue
    visited.add(current)
    for (const neighbor of adjacency.get(current) ?? []) {
      queue.push(neighbor)
    }
  }

  return null
}

/**
 * 连线验证 composable
 */
export function useConnectionValidator() {
  function validateConnection(connection: Connection): boolean {
    return getValidationError(connection) === null
  }

  return { validateConnection }
}
