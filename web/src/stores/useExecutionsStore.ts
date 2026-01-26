import { defineStore } from 'pinia'
import { ref } from 'vue'
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
 let ws: WebSocket | null = null
 async function fetchExecutions(workflowId?: string, projectId?: string) {
 loading.value = true
 error.value = null
 try {
 const params = new URLSearchParams
 if (workflowId)
 params.append('workflow_id', workflowId)
 if (projectId)
 params.append('project_id', projectId)
 const url = `/workflow-executions/${params.toString ? `?${params.toString}`: ''}`
 const data = await api.get<any>(url)
 executions.value = data.results || data
 }
 catch (e: any) {
 error.value = e.message
 console.error(e)
 }
 finally {
 loading.value = false
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
 console.error(e)
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
 function connectWebSocket(executionId: string) {
 if (ws) {
 ws.close
 }
 const protocol = window.location.protocol === 'https:' ? 'wss:': 'ws:'
 const wsUrl = `${protocol}//${window.location.host}/ws/workflow-executions/${executionId}/`
 ws = new WebSocket(wsUrl)
 ws.onopen = => {
 // WebSocket connected
 }
 ws.onmessage = (event) => {
 try {
 const data = JSON.parse(event.data)
 handleWebSocketMessage(data)
 }
 catch (e) {
 console.error('Failed to parse WebSocket message:', e)
 }
 }
 ws.onerror = (event) => {
 console.error('WebSocket error:', event)
 }
 ws.onclose = => {
 // WebSocket disconnected
 }
 }
 function disconnectWebSocket {
 if (ws) {
 ws.close
 ws = null
 }
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
 fetchExecutions,
 fetchExecution,
 pauseExecution,
 resumeExecution,
 cancelExecution,
 approveNode,
 rejectNode,
 connectWebSocket,
 disconnectWebSocket,
 }
})
