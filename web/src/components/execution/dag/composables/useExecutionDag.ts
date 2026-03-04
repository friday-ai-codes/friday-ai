/**
 * useExecutionDag — 将 workflow_definition + node_executions + timeline 合并为 Vue Flow 节点/边
 *
 * 独立于编辑器的 useWorkflowsStore，避免只读视图和编辑视图的状态冲突。
 */
import type { Node, Edge, NodeComponent } from '@vue-flow/core'
import { MarkerType } from '@vue-flow/core'
import { markRaw } from 'vue'
import { computed, type Ref } from 'vue'
import type {
 WorkflowExecution,
 NodeExecution,
 TimelineData,
 WorkflowDefinition,
} from '~/stores/useExecutionsStore'
import type { NodeCost } from '~/types/execution'
import GradientEdge from '~/components/workflow/editor/edges/GradientEdge.vue'
import ExecutionNode from '../ExecutionNode.vue'
/** Vue Flow 执行节点的 data 载荷类型 */
export interface ExecutionNodeData {
 nodeType: string
 name: string
 status: string
 duration: number | null
 startedAt: string | null
 isBottleneck: boolean
 bottleneckLevel: 'critical' | 'warning' | null
 nodeExecution: NodeExecution | null
 config: Record<string, unknown>
 /** 运行中节点的实时 elapsed 秒数（由 useNodeTimer 注入） */
 elapsed?: number
 /** 节点级成本数据（由页面层从 CostBreakdown 注入） */
 cost?: NodeCost
}
/** 自定义节点类型注册 */
export const executionNodeTypes: Record<string, NodeComponent> = {
 execution: markRaw(ExecutionNode) as unknown as NodeComponent,
}
/** 自定义边类型注册（复用编辑器的 GradientEdge） */
export const executionEdgeTypes = {
 gradient: markRaw(GradientEdge),
}
/**
 * 将 workflow_definition + node_executions + timeline 数据合并为 Vue Flow 格式。
 */
export function useExecutionDag(
 execution: Ref<WorkflowExecution | null>,
 timelineData: Ref<TimelineData | null>,
) {
 const dagNodes = computed<Node<ExecutionNodeData>>( => {
 const exec = execution.value
 if (!exec?.workflow_definition) return
 const definition: WorkflowDefinition = exec.workflow_definition
 const execMap = new Map<string, NodeExecution>(
 (exec.node_executions ?? ).map(ne => [ne.node, ne]),
 )
 const bottleneckMap = new Map(
 (timelineData.value?.nodes ?? )
 .filter(n => n.is_bottleneck)
 .map(n => [n.node_id, n]),
 )
 return definition.nodes.map(defNode => {
 const ne = execMap.get(defNode.id)
 const bn = bottleneckMap.get(defNode.id)
 return {
 id: defNode.id,
 type: 'execution',
 position: { ...defNode.position },
 data: {
 nodeType: defNode.node_type,
 name: defNode.name,
 status: ne?.status ?? 'pending',
 duration: ne?.duration ?? null,
 startedAt: ne?.started_at ?? null,
 isBottleneck: bn?.is_bottleneck ?? false,
 bottleneckLevel: bn?.bottleneck_level ?? null,
 nodeExecution: ne ?? null,
 config: defNode.config ?? {},
 },
 }
 })
 })
 const dagEdges = computed<Edge>( => {
 const exec = execution.value
 if (!exec?.workflow_definition) return
 const definition: WorkflowDefinition = exec.workflow_definition
 return definition.edges.map(defEdge => ({
 id: defEdge.id,
 source: defEdge.source,
 target: defEdge.target,
 sourceHandle: defEdge.sourcePort || 'default',
 targetHandle: defEdge.targetPort || 'default',
 type: 'gradient',
 markerEnd: MarkerType.ArrowClosed,
 }))
 })
 return { dagNodes, dagEdges }
}
