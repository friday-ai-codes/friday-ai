import type { Connection } from '@vue-flow/core'
import { useVueFlow } from '@vue-flow/core'
import { arePortShapesCompatible, resolvePortShape, shapeDisplayName } from './portShapes'

/**
 * i18n 翻译函数（vue-i18n Composer 的 `t`）。
 * 仅 Toast 文案路径需要；boolean 校验路径（isValidConnection）可不传。
 */
type Translator = (key: string, named?: Record<string, unknown>) => string

/**
 * 连线验证失败原因（用于 Toast 提示）。
 *
 * 校验顺序（前 3 条为既有逻辑，零回归）：防自连 → 四元组重复 → BFS 防环 →
 * 第 4 条「契约形状兼容」（SLOT-03，前端权威即时判定；后端 `_validate_port_shapes` 保存兜底）。
 *
 * `t` 用于第 4 条提示文案的中文 shape 名渲染；不传时（纯 boolean 路径）退化为
 * 内置中文模板（该串不展示给用户，仅用于使 boolean 判定为非法）。
 */
export function getValidationError(connection: Connection, t?: Translator): string | null {
  const { getEdges, findNode } = useVueFlow()

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

  // 第 4 条：契约形状兼容（前端权威；后端兜底）。
  // 解析两端 nodeType（node.data.nodeType 为权威来源）+ handle（?? 'default' 归一），
  // 取源 output / 目标 input 的 shape；空契约通配（缺类型/缺 shape）→ 不拦截（零回归）。
  const srcType = findNode(connection.source)?.data?.nodeType as string | undefined
  const tgtType = findNode(connection.target)?.data?.nodeType as string | undefined
  if (srcType && tgtType) {
    const srcShape = resolvePortShape(srcType, connection.sourceHandle ?? 'default', 'output')
    const tgtShape = resolvePortShape(tgtType, connection.targetHandle ?? 'default', 'input')
    if (!arePortShapesCompatible(srcShape, tgtShape)) {
      const source = shapeDisplayName(srcShape, t)
      const target = shapeDisplayName(tgtShape, t)
      if (t)
        return t('workflow.editor.slot.incompatibleBody', { source, target })
      // 无 t 注入时的内置回退（仅用于 boolean 非法判定，不向用户展示）。
      return `形状不兼容：「${source}」无法接入「${target}」`
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
