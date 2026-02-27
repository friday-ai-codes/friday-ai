import { useIntervalFn, useWebSocket } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import api from '~/api/client'
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
}
export const useExecutionsStore = defineStore('executions', => {
 const executions = ref<WorkflowExecution>
 const currentExecution = ref<WorkflowExecution | null>(null)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // WebSocket connection
 const wsUrl = ref<string | undefined>(undefined)
 const { data: wsData, close: wsClose, open: wsOpen, status: wsStatus } = useWebSocket(wsUrl, {
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
 catch (e: any) {
 error.value = e.message
 }
 finally {
 if (!silent) {
 loading.value = false
 }
 }
 }
 async function fetchExecution(id: string) {
 loading.value = true
 error.value = null
 try {
 currentExecution.value = await api.get<WorkflowExecution>(`/workflow-executions/${id}/`)
 }
 catch (e: any) {
 error.value = e.message
 }
 finally {
 loading.value = false
 }
 }
 async function pauseExecution(id: string) {
 try {
 await api.post(`/workflow-executions/${id}/pause/`)
 if (currentExecution.value?.id === id) {
 currentExecution.value.status = 'paused'
 }
 }
 catch (e: any) {
 error.value = e.message
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
 catch (e: any) {
 error.value = e.message
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
 catch (e: any) {
 error.value = e.message
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
 catch (e: any) {
 error.value = e.message
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
 catch (e: any) {
 error.value = e.message
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
 catch (e: any) {
 error.value = e.message
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
 // Refresh full data on execution complete
 if (event === 'execution_completed' || event === 'execution_failed') {
 fetchExecution(execution_id)
 }
 }
 return {
 executions,
 currentExecution,
 loading,
 error,
 stats,
 hasActiveExecutions,
 fetchExecutions,
 fetchExecution,
 pauseExecution,
 resumeExecution,
 cancelExecution,
 approveNode,
 rejectNode,
 triggerNode,
 connectWebSocket,
 disconnectWebSocket,
 startAutoRefresh,
 stopAutoRefresh,
 wsStatus,
 }
})
