import type { Edge, Node } from '@vue-flow/core'
import type { WorkflowEdgeStore, WorkflowNodeStore } from '~/types/workflow/store'
import { MarkerType } from '@vue-flow/core'

/** Vue Flow Node 的 data 载荷类型 */
interface WorkflowNodeData {
  nodeType: string
  shortId: string
  name: string
  description: string
  config: Record<string, unknown>
  onError: 'abort' | 'retry' | 'ignore'
  retryTimes: number
  retryDelay: number
  nodeTimeoutSeconds: number | null
  fallbackValues: Record<string, unknown> | null
  runCondition: Record<string, unknown> | null
  metadata: Record<string, unknown>
}

/** Vue Flow Edge 的 data 载荷类型 */
interface WorkflowEdgeData {
  condition: Record<string, unknown> | null
  /** 源节点类型（派生字段，供边 "+" 菜单按上下游类型过滤可选节点用，不入 store） */
  sourceType?: string
  /** 目标节点类型（派生字段，同上） */
  targetType?: string
}

/**
 * 将 Pinia Store 节点转为 Vue Flow 节点。
 * nodeType 映射到 Vue Flow 的 type 字段，用于查找自定义节点组件。
 * 其余业务字段全部放入 data 中，保证往返转换无丢失。
 *
 * SLOT-04 父子映射：store 节点若带 `metadata.parentNodeId`（附着子节点），
 * 输出附 `parentNode: <parentId>` + `extent: 'parent'`（Vue Flow 原生包含/级联拖拽/相对定位）。
 *
 * 数据契约命门（WARNING 1，跨 plan 固化）：top-level `parentNode` 与 `data.metadata`
 * （含 `parentNodeId`）**同源并存**——`data.metadata` 逐字透传既有 storeNode.metadata，
 * 不为提 parentNode 到顶层而从 metadata 删改 parentNodeId。下游 93-05 经
 * `props.data.metadata.parentNodeId` 判附着徽标，故 `node.data.metadata.parentNodeId`
 * 是该判定的唯一权威来源，必须随节点透传。
 *
 * 排序命门：返回前把带 parent 的子节点排到其父之后（先无 parent 再有 parent 的两趟稳定排序），
 * 否则 Vue Flow 报 "parent node not found"。
 */
export function toVueFlowNodes(storeNodes: WorkflowNodeStore[]): Node<WorkflowNodeData>[] {
  const vfNodes = storeNodes.map((storeNode) => {
    const parentNodeId = storeNode.metadata?.parentNodeId
    const node: Node<WorkflowNodeData> = {
      id: storeNode.id,
      type: storeNode.nodeType,
      position: { ...storeNode.position },
      data: {
        nodeType: storeNode.nodeType,
        shortId: storeNode.shortId,
        name: storeNode.name,
        description: storeNode.description,
        config: storeNode.config,
        onError: storeNode.onError,
        retryTimes: storeNode.retryTimes,
        retryDelay: storeNode.retryDelay,
        nodeTimeoutSeconds: storeNode.nodeTimeoutSeconds,
        fallbackValues: storeNode.fallbackValues,
        runCondition: storeNode.runCondition,
        // 同源透传：含 parentNodeId 在内的全部 metadata 逐字保留（93-05 徽标读取来源）
        metadata: storeNode.metadata,
      },
    }
    // 仅附着子节点提 parentNode + extent 到顶层（Vue Flow 包含语义）；不改 data.metadata
    if (typeof parentNodeId === 'string' && parentNodeId) {
      node.parentNode = parentNodeId
      node.extent = 'parent'
    }
    return node
  })

  // 父先子排序（Vue Flow 硬约束）：稳定两趟——先无 parentNode 的，再有 parentNode 的
  return [
    ...vfNodes.filter(n => !n.parentNode),
    ...vfNodes.filter(n => n.parentNode),
  ]
}

/**
 * 将 Pinia Store 边转为 Vue Flow 边。
 * sourcePort/targetPort 映射到 sourceHandle/targetHandle，空值 fallback 到 "default"。
 * 使用自定义 gradient 边类型 + 箭头标记。
 *
 * 可选 `storeNodes`：传入后在 edge.data 上派生 sourceType/targetType（两端节点类型），
 * 供边 "+" 菜单按上下游类型过滤可选节点；取不到留 undefined。派生字段不回写 store。
 */
export function toVueFlowEdges(
  storeEdges: WorkflowEdgeStore[],
  storeNodes?: WorkflowNodeStore[],
): Edge<WorkflowEdgeData>[] {
  const typeById = new Map<string, string>()
  if (storeNodes) {
    for (const node of storeNodes)
      typeById.set(node.id, node.nodeType)
  }

  return storeEdges.map(storeEdge => ({
    id: storeEdge.id,
    source: storeEdge.source,
    target: storeEdge.target,
    sourceHandle: storeEdge.sourcePort || 'default',
    targetHandle: storeEdge.targetPort || 'default',
    label: storeEdge.label,
    data: {
      condition: storeEdge.condition,
      sourceType: typeById.get(storeEdge.source),
      targetType: typeById.get(storeEdge.target),
    },
    type: 'gradient',
    markerEnd: MarkerType.ArrowClosed,
  }))
}

/**
 * 将 Vue Flow 节点转回 Pinia Store 节点（位置同步用）。
 * 从 data 中还原所有业务字段。
 */
export function fromVueFlowNodes(vfNodes: Node<WorkflowNodeData>[]): WorkflowNodeStore[] {
  return vfNodes.map((vfNode) => {
    const d = vfNode.data!
    return {
      id: vfNode.id,
      shortId: d.shortId,
      nodeType: d.nodeType,
      name: d.name,
      description: d.description,
      position: vfNode.position,
      config: d.config,
      onError: d.onError,
      retryTimes: d.retryTimes,
      retryDelay: d.retryDelay,
      nodeTimeoutSeconds: d.nodeTimeoutSeconds,
      fallbackValues: d.fallbackValues,
      runCondition: d.runCondition,
      metadata: d.metadata,
    }
  })
}

/**
 * 将 Vue Flow 边转回 Pinia Store 边。
 * sourceHandle/targetHandle 映射回 sourcePort/targetPort，空值 fallback 到 "default"。
 */
export function fromVueFlowEdges(vfEdges: Edge<WorkflowEdgeData>[]): WorkflowEdgeStore[] {
  return vfEdges.map(vfEdge => ({
    id: vfEdge.id,
    source: vfEdge.source,
    target: vfEdge.target,
    sourcePort: vfEdge.sourceHandle ?? 'default',
    targetPort: vfEdge.targetHandle ?? 'default',
    label: vfEdge.label as string | undefined,
    condition: vfEdge.data?.condition ?? null,
  }))
}
