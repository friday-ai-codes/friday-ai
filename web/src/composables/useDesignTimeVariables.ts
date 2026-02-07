import type { WorkflowEdge, WorkflowNode } from '~/types/workflow/store'
import type { Ref } from 'vue'
import { computed } from 'vue'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
/**
 * 设计态变量项
 */
export interface DesignTimeVariable {
 /** 输出端口名称 */
 key: string
 /** 完整变量路径 nodes.{nodeId}.{outputName} */
 path: string
 /** 显示标签「阶段名 - 变量名」 */
 label: string
 /** 来源节点 ID */
 nodeId: string
 /** 节点显示名称 */
 nodeLabel: string
 /** 输出端口 label */
 outputLabel: string
 /** 端口类型 */
 type: string
 /** 端口描述 */
 description?: string
}
/**
 * 变量分类
 */
export interface VariableCategory {
 category: string
 categoryLabel: string
 icon: any
 color: string
 items: DesignTimeVariable
}
/**
 * 获取当前节点的所有上游节点（通过 DAG 反向遍历）
 */
function getUpstreamNodes(
 nodeId: string,
 nodes: WorkflowNode,
 edges: WorkflowEdge,
): WorkflowNode {
 const visited = new Set<string>
 const result: WorkflowNode =
 const nodeMap = new Map(nodes.map(n => [n.id, n]))
 function traverse(id: string) {
 if (visited.has(id)) return
 visited.add(id)
 // 找到所有指向当前节点的边（target === id）
 const incomingEdges = edges.filter(e => e.target === id)
 for (const edge of incomingEdges) {
 const sourceNode = nodeMap.get(edge.source)
 if (sourceNode) {
 result.push(sourceNode)
 traverse(edge.source)
 }
 }
 }
 traverse(nodeId)
 // 按执行顺序排列（上游节点在前）
 return result.reverse
}
/**
 * 设计态变量 Composable
 *
 * 在工作流编辑器中，根据当前节点在 DAG 中的位置，
 * 自动获取所有上游节点的输出变量，并以「阶段名 - 变量名」格式展示。
 *
 * @example
 * ```ts
 * const nodes = ref<WorkflowNode>
 * const edges = ref<WorkflowEdge>
 * const currentNodeId = ref<string | null>('node-2')
 *
 * const { upstreamNodes, designTimeVariables } = useDesignTimeVariables(
 * nodes,
 * edges,
 * currentNodeId
 * )
 *
 * // designTimeVariables 返回格式化的变量列表
 * // 如 [{ label: '召回上下文 - 检索结果', path: 'nodes.xxx.formatted_context', ... }]
 * ```
 */
export function useDesignTimeVariables(
 workflowNodes: Ref<WorkflowNode>,
 workflowEdges: Ref<WorkflowEdge>,
 currentNodeId: Ref<string | null>,
) {
 const nodeTypesStore = useNodeTypesStore
 // 获取当前节点的所有上游节点
 const upstreamNodes = computed( => {
 if (!currentNodeId.value) return
 return getUpstreamNodes(
 currentNodeId.value,
 workflowNodes.value,
 workflowEdges.value,
 )
 })
 // 构建设计态变量列表
 const designTimeVariables = computed(: DesignTimeVariable => {
 const variables: DesignTimeVariable =
 for (const node of upstreamNodes.value) {
 // 获取节点类型（优先 data.node_type，其次 type）
 const nodeTypeKey = node.data?.node_type || node.type
 if (!nodeTypeKey) continue
 const nodeTypeDef = nodeTypesStore.getNodeType(nodeTypeKey)
 if (!nodeTypeDef) continue
 // 节点显示名称：优先用户自定义名称，其次节点类型定义的显示名
 const nodeLabel = node.data?.name || node.label || nodeTypeDef.display_name
 // 遍历该节点的所有输出端口
 for (const output of nodeTypeDef.outputs) {
 variables.push({
 key: output.name,
 path: `nodes.${node.id}.${output.name}`,
 label: `${nodeLabel} - ${output.label}`,
 nodeId: node.id,
 nodeLabel,
 outputLabel: output.label,
 type: output.type,
 description: output.description,
 })
 }
 }
 return variables
 })
 // 按分类分组的变量列表（兼容 VariablePicker 的格式）
 const designTimeVariablesByCategory = computed(: VariableCategory => {
 const variables = designTimeVariables.value
 if (variables.length === 0) return
 // 将所有节点输出变量归入「节点输出」分类
 return [{
 category: 'nodes',
 categoryLabel: '节点输出',
 icon: null, // 由组件提供图标
 color: 'text-purple-500',
 items: variables,
 }]
 })
 return {
 /** 上游节点列表 */
 upstreamNodes,
 /** 设计态变量列表（扁平） */
 designTimeVariables,
 /** 设计态变量列表（按分类） */
 designTimeVariablesByCategory,
 }
}
