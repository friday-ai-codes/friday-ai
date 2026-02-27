import { computed, watch } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { storeToRefs } from 'pinia'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
import type { NodeExecutionStatus } from '../nodes/composables/useNodeStyle'
/** 将后端节点执行状态映射为前端视觉状态 */
export function mapBackendStatus(backendStatus: string): NodeExecutionStatus {
 switch (backendStatus) {
 case 'running': return 'running'
 case 'completed': return 'success'
 case 'failed': return 'failed'
 case 'skipped': return 'skipped'
 default: return 'idle'
 }
}
/**
 * WebSocket 执行事件到 Vue Flow 画布视觉状态的桥接层。
 *
 * 职责：
 * - watch currentExecution.node_executions 变化，增量更新节点/边视觉状态
 * - 执行切换时自动重置所有节点/边为 idle
 * - 暴露 WS 断线检测 computed
 */
export function useExecutionStatus {
 const { updateNodeData, getEdges, getNodes } = useVueFlow
 const executionsStore = useExecutionsStore
 const { currentExecution } = storeToRefs(executionsStore)
 /** WS 断线检测：当连接非 OPEN 且有活跃执行时为 true */
 const isWsDisconnected = computed( =>
 executionsStore.wsStatus !== 'OPEN' && currentExecution.value !== null,
 )
 /** 根据节点状态更新其入边的 flowing/skipped 视觉属性 */
 function updateEdgesForNode(nodeId: string, status: NodeExecutionStatus) {
 for (const edge of getEdges.value) {
 if (edge.target !== nodeId) continue
 if (status === 'running') {
 edge.data = { ...edge.data, flowing: true, skipped: false }
 }
 else if (status === 'success' || status === 'failed') {
 edge.data = { ...edge.data, flowing: false }
 }
 else if (status === 'skipped') {
 edge.data = { ...edge.data, flowing: false, skipped: true }
 }
 }
 }
 /** 重置所有节点和边为 idle 初始状态 */
 function resetAllStatuses {
 for (const node of getNodes.value) {
 updateNodeData(node.id, { executionStatus: 'idle' })
 }
 for (const edge of getEdges.value) {
 edge.data = { ...edge.data, flowing: false, skipped: false }
 }
 }
 // 执行切换时自动重置所有状态（注册顺序在前，确保先重置再更新）
 watch(
 => currentExecution.value?.id,
 (newId, oldId) => {
 if (newId && newId !== oldId) {
 resetAllStatuses
 }
 },
 )
 // 增量节点状态更新：watch node_executions 数组的深层变化
 watch(
 => currentExecution.value?.node_executions,
 (nodeExecs) => {
 if (!nodeExecs) return
 for (const ne of nodeExecs) {
 const status = mapBackendStatus(ne.status)
 updateNodeData(ne.node, { executionStatus: status })
 updateEdgesForNode(ne.node, status)
 }
 },
 { deep: true },
 )
 return { resetAllStatuses, isWsDisconnected }
}
