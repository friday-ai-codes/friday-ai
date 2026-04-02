import type { SubStep } from '~/types/execution'
import { useIntervalFn, useWebSocket } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import api from '~/api/client'
import { extractErrorMessage } from '~/composables/useErrorHandler'
export interface NodeExecution {
 id: string
 node: string
 node_name: string
 node_type: string
 status: string
 input_data: Record<string, any>
 output_data: Record<string, any>
 error_message: string
 error_traceback: string
 attempt: number
 approval_data: Record<string, any>
 container_id: string
 container_logs: string
 duration: number | null
 created_at: string
 started_at: string | null
 completed_at: string | null
 sub_step_progress: { completed: number, total: number } | null
}
export interface WorkflowDefinitionNode {
 id: string
 name: string
 node_type: string
 position: { x: number, y: number }
 config: Record<string, unknown>
}
export interface WorkflowDefinitionEdge {
 id: string
 source: string
 target: string
 sourcePort: string
 targetPort: string
}
export interface WorkflowDefinition {
 nodes: WorkflowDefinitionNode
 edges: WorkflowDefinitionEdge
}
export interface TimelineNode {
 node_id: string
 node_name: string
 node_type: string
 status: string
 started_at: string | null
 completed_at: string | null
 duration_seconds: number | null
 is_bottleneck: boolean
 bottleneck_level: 'critical' | 'warning' | null
}
export interface TimelineData {
 nodes: TimelineNode
 summary: {
 total_duration_seconds: number | null
 total_nodes: number
 avg_node_duration_seconds: number | null
 bottleneck_nodes: number
 }
}
export interface WorkflowExecution {
 id: string
 workflow: string
 workflow_name: string
 task: string | null
 status: string
 trigger_type: string
 triggered_by: string | null
 triggered_by_name: string | null
 trigger_data: Record<string, any>
 trigger_log_id: string | null
 resumed_from: string | null
 workflow_definition: WorkflowDefinition | null
 context: Record<string, any>
 input_data: Record<string, any>
 output_data: Record<string, any>
 error_message: string
 error_node_id: string | null
 total_nodes: number
 completed_nodes: number
 failed_nodes: number
 skipped_nodes: number
 node_executions: NodeExecution
 duration: number | null
 progress: number
 created_at: string
 started_at: string | null
 completed_at: string | null
 timeout_at: string | null
 /** 是否为调试执行 */
 is_debug?: boolean
 /** 调试模式下当前暂停在哪个节点的 ID */
 debug_paused_at_node?: string | null
}
export const useExecutionsStore = defineStore('executions', => {
 const executions = ref<WorkflowExecution>
 const currentExecution = ref<WorkflowExecution | null>(null)
 const timelineData = ref<TimelineData | null>(null)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // 子步骤缓存（key: node_execution_id）
 const subSteps = ref<Record<string, SubStep>>({})
 // WebSocket connection
 const wsUrl = ref<string | undefined>(undefined)
 const { data: wsData, close: wsClose, open: wsOpen, status: wsStatus, send: wsSend } = useWebSocket(wsUrl, {
 immediate: false,
 autoReconnect: {
 retries: 3,
 delay: 1000,
 },
 })
 // Watch WebSocket messages
 watch(wsData, (data) => {
 if (data) {
 try {
 const parsed = JSON.parse(data)
 handleWebSocketMessage(parsed)
 }
 catch {
 // intentionally ignored
 }
 }
 })
 // Computed stats
 const stats = computed( => ({
 total: executions.value.length,
 running: executions.value.filter(e => e.status === 'running').length,
 pending: executions.value.filter(e => e.status === 'pending').length,
 waitingApproval: executions.value.filter(e =>
 e.status === 'waiting_approval'
 || e.node_executions?.some(n => n.status === 'waiting_approval'),
 ).length,
 completed: executions.value.filter(e => e.status === 'completed').length,
 failed: executions.value.filter(e => e.status === 'failed').length,
 }))
 // Check if there are active executions
 const hasActiveExecutions = computed( =>
 stats.value.running > 0 || stats.value.pending > 0,
 )
 // Auto-refresh using useIntervalFn
 const { pause: stopAutoRefresh, resume: startAutoRefresh } = useIntervalFn(
 => {
 if (hasActiveExecutions.value) {
 fetchExecutions
 }
 },
 5000,
 { immediate: false },
 )
 async function fetchExecutions(workflowId?: string, projectId?: string, createdAfter?: string, silent = false) {
 // silent 模式下不显示 loading 状态，避免页面抖动
 if (!silent) {
 loading.value = true
 }
 error.value = null
 try {
 // 构建查询参数对象，让 api.get 处理 URL 拼接
 const params: Record<string, string> = {}
 if (workflowId)
 params.workflow_id = workflowId
 if (projectId)
 params.project_id = projectId
 if (createdAfter)
 params.created_after = createdAfter
 const data = await api.get<any>('/workflow-executions/', params)
 executions.value = data.results || data
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 }
 finally {
 if (!silent) {
 loading.value = false
 }
 }
 }
 async function fetchExecution(id: string) {
 // 切换 execution 时清理 subSteps 缓存，防止残留旧数据
 subSteps.value = {}
 loading.value = true
 error.value = null
 try {
 currentExecution.value = await api.get<WorkflowExecution>(`/workflow-executions/${id}/`)
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 }
 finally {
 loading.value = false
 }
 }
 async function fetchTimeline(id: string) {
 try {
 timelineData.value = await api.get<TimelineData>(`/workflow-executions/${id}/timeline/`)
 }
 catch {
 // timeline 数据是辅助信息，获取失败不阻塞主流程
 timelineData.value = null
 }
 }
 async function pauseExecution(id: string) {
 try {
 await api.post(`/workflow-executions/${id}/pause/`)
 if (currentExecution.value?.id === id) {
 currentExecution.value.status = 'paused'
 }
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 throw e
 }
 }
 async function resumeExecution(id: string) {
 try {
 await api.post(`/workflow-executions/${id}/resume/`)
 if (currentExecution.value?.id === id) {
 currentExecution.value.status = 'running'
 }
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 throw e
 }
 }
 async function cancelExecution(id: string) {
 try {
 await api.post(`/workflow-executions/${id}/cancel/`)
 if (currentExecution.value?.id === id) {
 currentExecution.value.status = 'cancelled'
 }
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 throw e
 }
 }
 async function approveNode(nodeExecutionId: string, comment: string = '') {
 try {
 await api.post(`/node-executions/${nodeExecutionId}/approve/`, { comment })
 // Refresh execution to get updated state
 if (currentExecution.value) {
 await fetchExecution(currentExecution.value.id)
 }
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 throw e
 }
 }
 async function rejectNode(nodeExecutionId: string, comment: string = '') {
 try {
 await api.post(`/node-executions/${nodeExecutionId}/reject/`, { comment })
 // Refresh execution to get updated state
 if (currentExecution.value) {
 await fetchExecution(currentExecution.value.id)
 }
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 throw e
 }
 }
 async function triggerNode(nodeExecutionId: string, inputData: Record<string, any> = {}) {
 try {
 await api.post(`/node-executions/${nodeExecutionId}/trigger/`, { input_data: inputData })
 // Refresh execution to get updated state
 if (currentExecution.value) {
 await fetchExecution(currentExecution.value.id)
 }
 }
 catch (e: unknown) {
 error.value = extractErrorMessage(e)
 throw e
 }
 }
 function connectWebSocket(executionId: string) {
 // Close existing connection by setting new URL
 const protocol = window.location.protocol === 'https:' ? 'wss:': 'ws:'
 wsUrl.value = `${protocol}//${window.location.host}/ws/workflow-executions/${executionId}/`
 wsOpen
 }
 function disconnectWebSocket {
 wsClose
 wsUrl.value = undefined
 }
 /** 通过 WS 发送调试操作命令（release/skip/mock） */
 function sendDebugAction(action: 'release' | 'skip' | 'mock', data: Record<string, any> = {}) {
 wsSend(JSON.stringify({
 type: 'debug_action',
 action,
 data,
 }))
 }
 /** Phase: 发送断点管理消息 */
 function sendBreakpointAction(type: 'set_breakpoint' | 'remove_breakpoint', nodeId: string) {
 wsSend(JSON.stringify({ type, node_id: nodeId }))
 }
 /** Phase: 发送调试模式切换消息 */
 function sendDebugModeSwitch(mode: 'step' | 'breakpoint') {
 wsSend(JSON.stringify({ type: 'set_debug_mode', mode }))
 }
 function handleWebSocketMessage(data: any) {
 if (!currentExecution.value)
 return
 const { event, execution_id, status, node_id, node_status } = data
 // Update execution status
 if (status && currentExecution.value.id === execution_id) {
 currentExecution.value.status = status
 }
 // Update node execution status
 if (node_id && node_status) {
 const nodeExec = currentExecution.value.node_executions.find(
 ne => ne.node === node_id,
 )
 if (nodeExec) {
 nodeExec.status = node_status
 }
 }
 // Update progress counters based on event
 if (event === 'node_completed') {
 currentExecution.value.completed_nodes++
 currentExecution.value.progress
 = ((currentExecution.value.completed_nodes + currentExecution.value.skipped_nodes)
 / currentExecution.value.total_nodes)
 * 100
 }
 else if (event === 'node_failed') {
 currentExecution.value.failed_nodes++
 }
 else if (event === 'node_skipped') {
 currentExecution.value.skipped_nodes++
 currentExecution.value.progress
 = ((currentExecution.value.completed_nodes + currentExecution.value.skipped_nodes)
 / currentExecution.value.total_nodes)
 * 100
 }
 // 处理调试暂停事件
 if (event === 'node_debug_paused') {
 currentExecution.value.debug_paused_at_node = node_id || null
 }
 // 处理调试操作确认（清除暂停状态）
 if (event === 'debug_action_ack' || data.type === 'debug_action_ack') {
 currentExecution.value.debug_paused_at_node = null
 }
 // Phase: 断点/模式 ack 确认（状态由页面层 optimistic 管理，此处仅做日志）
 if (data.type === 'breakpoint_ack' || data.type === 'debug_mode_ack') {
 // ack 已收到，前端已做 optimistic update，无需额外处理
 }
 // Refresh full data on execution complete
 if (event === 'execution_completed' || event === 'execution_failed') {
 fetchExecution(execution_id)
 }
 // 处理子步骤实时更新
 if (data.event === 'sub_step.update') {
 const { node_execution_id, data: stepData } = data
 if (!subSteps.value[node_execution_id]) {
 subSteps.value[node_execution_id] =
 }
 const steps = subSteps.value[node_execution_id]
 const existingIdx = steps.findIndex(s => s.id === stepData.id)
 if (existingIdx >= 0) {
 steps[existingIdx] = stepData
 }
 else {
 steps.push(stepData)
 steps.sort((a: SubStep, b: SubStep) => a.step_order - b.step_order)
 }
 // 更新 NodeExecution 的 sub_step_progress
 if (stepData.progress && currentExecution.value) {
 const nodeExec = currentExecution.value.node_executions.find(
 ne => ne.id === node_execution_id,
 )
 if (nodeExec) {
 nodeExec.sub_step_progress = stepData.progress
 }
 }
 }
 }
 async function fetchSubSteps(nodeExecutionId: string) {
 try {
 const data = await api.get<SubStep>(`/node-executions/${nodeExecutionId}/sub-steps/`)
 subSteps.value[nodeExecutionId] = data
 }
 catch {
 // 静默失败，子步骤是辅助信息
 }
 }
 return {
 executions,
 currentExecution,
 timelineData,
 loading,
 error,
 stats,
 hasActiveExecutions,
 fetchExecutions,
 fetchExecution,
 fetchTimeline,
 pauseExecution,
 resumeExecution,
 cancelExecution,
 approveNode,
 rejectNode,
 triggerNode,
 connectWebSocket,
 disconnectWebSocket,
 sendDebugAction,
 sendBreakpointAction,
 sendDebugModeSwitch,
 startAutoRefresh,
 stopAutoRefresh,
 wsStatus,
 subSteps,
 fetchSubSteps,
 }
})
