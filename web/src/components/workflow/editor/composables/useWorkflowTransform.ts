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
 timeout: number | null
 retryCount: number
 retryDelay: number
 runCondition: Record<string, unknown> | null
 metadata: Record<string, unknown>
}
/** Vue Flow Edge 的 data 载荷类型 */
interface WorkflowEdgeData {
 condition: Record<string, unknown> | null
}
/**
 * 将 Pinia Store 节点转为 Vue Flow 节点。
 * nodeType 映射到 Vue Flow 的 type 字段，用于查找自定义节点组件。
 * 其余业务字段全部放入 data 中，保证往返转换无丢失。
 */
export function toVueFlowNodes(storeNodes: WorkflowNodeStore): Node<WorkflowNodeData> {
 return storeNodes.map(storeNode => ({
 id: storeNode.id,
 type: storeNode.nodeType,
 position: { ...storeNode.position },
 data: {
 nodeType: storeNode.nodeType,
 shortId: storeNode.shortId,
 name: storeNode.name,
 description: storeNode.description,
 config: storeNode.config,
 timeout: storeNode.timeout,
 retryCount: storeNode.retryCount,
 retryDelay: storeNode.retryDelay,
 runCondition: storeNode.runCondition,
 metadata: storeNode.metadata,
 },
 }))
}
/**
 * 将 Pinia Store 边转为 Vue Flow 边。
 * sourcePort/targetPort 映射到 sourceHandle/targetHandle，空值 fallback 到 "default"。
 * 使用自定义 gradient 边类型 + 箭头标记。
 */
export function toVueFlowEdges(storeEdges: WorkflowEdgeStore): Edge<WorkflowEdgeData> {
 return storeEdges.map(storeEdge => ({
 id: storeEdge.id,
 source: storeEdge.source,
 target: storeEdge.target,
 sourceHandle: storeEdge.sourcePort || 'default',
 targetHandle: storeEdge.targetPort || 'default',
 label: storeEdge.label,
 data: { condition: storeEdge.condition },
 type: 'gradient',
 markerEnd: MarkerType.ArrowClosed,
 }))
}
/**
 * 将 Vue Flow 节点转回 Pinia Store 节点（位置同步用）。
 * 从 data 中还原所有业务字段。
 */
export function fromVueFlowNodes(vfNodes: Node<WorkflowNodeData>): WorkflowNodeStore {
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
 timeout: d.timeout,
 retryCount: d.retryCount,
 retryDelay: d.retryDelay,
 runCondition: d.runCondition,
 metadata: d.metadata,
 }
 })
}
/**
 * 将 Vue Flow 边转回 Pinia Store 边。
 * sourceHandle/targetHandle 映射回 sourcePort/targetPort，空值 fallback 到 "default"。
 */
export function fromVueFlowEdges(vfEdges: Edge<WorkflowEdgeData>): WorkflowEdgeStore {
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
