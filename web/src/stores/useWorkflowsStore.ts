import type { Edge, Node } from '@vue-flow/core'
import type { ManualTriggerResponse } from '~/types'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import client from '~/api/client'
export interface WorkflowNode {
 id: string
 node_type: string
 name: string
 description: string
 position_x: number
 position_y: number
 config: Record<string, any>
 timeout: number | null
 retry_count: number
 retry_delay: number
 run_condition: Record<string, any> | null
 metadata: Record<string, any>
 created_at: string
 updated_at: string
}
export interface WorkflowEdge {
 id: string
 source_node: string
 target_node: string
 source_handle: string
 target_handle: string
 condition: Record<string, any> | null
 label: string
 style: Record<string, any>
 created_at: string
}
export interface Workflow {
 id: string
 name: string
 description: string
 icon: string
 project: string
 project_name: string
 created_by: string | null
 created_by_name: string | null
 trigger_type: 'manual' | 'webhook' | 'schedule' | 'event'
 trigger_config: Record<string, any>
 is_active: boolean
 is_template: boolean
 max_concurrent_executions: number
 default_timeout: number
 metadata: Record<string, any>
 nodes: WorkflowNode
 edges: WorkflowEdge
 execution_count: number
 last_execution: { id: string, status: string, created_at: string } | null
 created_at: string
 updated_at: string
}
const DRAFT_KEY_PREFIX = 'friday-workflow-draft-'
export const useWorkflowsStore = defineStore('workflows', => {
 const workflows = ref<Workflow>
 const currentWorkflow = ref<Workflow | null>(null)
 const loading = ref(false)
 const saving = ref(false)
 const error = ref<string | null>(null)
 // Selected node for configuration panel
 const selectedNodeId = ref<string | null>(null)
 // Undo/Redo history
 const history = ref<{ nodes: Node, edges: Edge }>
 const historyIndex = ref(-1)
 const maxHistorySize = 50
 // Vue Flow nodes and edges (for canvas)
 const nodes = ref<Node>
 const edges = ref<Edge>
 // Unsaved changes tracking
 const hasUnsavedChanges = ref(false)
 // Computed
 const canUndo = computed( => historyIndex.value > 0)
 const canRedo = computed( => historyIndex.value < history.value.length - 1)
 const selectedNode = computed(: Node | null => {
 if (!selectedNodeId.value)
 return null
 return nodes.value.find(n => n.id === selectedNodeId.value) || null
 })
 // Convert backend nodes to Vue Flow format
 function toVueFlowNodes(workflowNodes: WorkflowNode): Node {
 return workflowNodes.map(node => ({
 id: node.id,
 type: node.node_type,
 position: { x: node.position_x, y: node.position_y },
 label: node.name,
 data: {
 node_type: node.node_type,
 name: node.name,
 description: node.description,
 config: node.config,
 timeout: node.timeout,
 retry_count: node.retry_count,
 retry_delay: node.retry_delay,
 run_condition: node.run_condition,
 metadata: node.metadata,
 },
 }))
 }
 // Convert backend edges to Vue Flow format
 function toVueFlowEdges(workflowEdges: WorkflowEdge): Edge {
 return workflowEdges.map(edge => ({
 id: edge.id,
 source: edge.source_node,
 target: edge.target_node,
 sourceHandle: edge.source_handle,
 targetHandle: edge.target_handle,
 label: edge.label,
 data: {
 condition: edge.condition,
 },
 }))
 }
 // 根据节点类型获取默认配置
 function getDefaultConfig(nodeType: string): Record<string, any> {
 const defaults: Record<string, Record<string, any>> = {
 ai_prompt: {
 user_prompt: '{{global.description}}',
 model: 'claude-3-5-sonnet-20241022',
 temperature: 0.7,
 max_tokens: 4096,
 output_format: 'text',
 },
 ai_coding_dispatcher: {
 max_tasks: 5,
 task_granularity: 'medium',
 include_tests: true,
 auto_assign_repos: false,
 },
 feishu_event_trigger: {
 event_types:,
 },
 fetch_work_item: {
 work_item_id: '{{input.work_item_id}}',
 extract_fields: ['description', 'title'],
 },
 }
 return defaults[nodeType] || {}
 }
 // Convert Vue Flow nodes back to backend format
 function toBackendNodes(vueFlowNodes: Node): Partial<WorkflowNode> {
 return vueFlowNodes.map((node) => {
 const nodeType = node.type || node.data?.node_type
 const defaultConfig = getDefaultConfig(nodeType)
 // 合并默认配置和用户配置，用户配置优先
 const config = { ...defaultConfig, ...node.data?.config }
 return {
 id: node.id,
 node_type: nodeType,
 name: node.data?.name || node.label || 'Untitled',
 description: node.data?.description || '',
 position_x: node.position.x,
 position_y: node.position.y,
 config,
 timeout: node.data?.timeout || null,
 retry_count: node.data?.retry_count || 0,
 retry_delay: node.data?.retry_delay || 60,
 run_condition: node.data?.run_condition || null,
 metadata: node.data?.metadata || {},
 }
 })
 }
 // Convert Vue Flow edges back to backend format
 function toBackendEdges(vueFlowEdges: Edge): Partial<WorkflowEdge> {
 return vueFlowEdges.map(edge => ({
 source_node_id: edge.source,
 target_node_id: edge.target,
 source_handle: edge.sourceHandle || 'default',
 target_handle: edge.targetHandle || 'default',
 condition: edge.data?.condition || null,
 label: typeof edge.label === 'string' ? edge.label: '',
 }))
 }
 // History management
 function saveToHistory {
 // Remove any redo history
 if (historyIndex.value < history.value.length - 1) {
 history.value = history.value.slice(0, historyIndex.value + 1)
 }
 // Add current state
 history.value.push({
 nodes: JSON.parse(JSON.stringify(nodes.value)),
 edges: JSON.parse(JSON.stringify(edges.value)),
 })
 // Limit history size
 if (history.value.length > maxHistorySize) {
 history.value.shift
 }
 else {
 historyIndex.value++
 }
 // Mark as having unsaved changes
 hasUnsavedChanges.value = true
 }
 function undo {
 if (!canUndo.value)
 return
 historyIndex.value--
 const state = history.value[historyIndex.value]
 nodes.value = JSON.parse(JSON.stringify(state.nodes))
 edges.value = JSON.parse(JSON.stringify(state.edges))
 }
 function redo {
 if (!canRedo.value)
 return
 historyIndex.value++
 const state = history.value[historyIndex.value]
 nodes.value = JSON.parse(JSON.stringify(state.nodes))
 edges.value = JSON.parse(JSON.stringify(state.edges))
 }
 // API calls
 async function fetchWorkflows(projectId?: string) {
 loading.value = true
 error.value = null
 try {
 const params: Record<string, string> = {}
 if (projectId)
 params.project_id = projectId
 const data = await client.get<any>('/workflows/', params)
 workflows.value = data.results || data
 }
 catch (e: any) {
 error.value = e.message
 console.error(e)
 }
 finally {
 loading.value = false
 }
 }
 async function fetchWorkflow(id: string) {
 loading.value = true
 error.value = null
 try {
 const workflow = await client.get<Workflow>(`/workflows/${id}/`)
 currentWorkflow.value = workflow
 // Convert to Vue Flow format
 nodes.value = toVueFlowNodes(workflow.nodes || )
 edges.value = toVueFlowEdges(workflow.edges || )
 // Initialize history
 history.value = [{ nodes: JSON.parse(JSON.stringify(nodes.value)), edges: JSON.parse(JSON.stringify(edges.value)) }]
 historyIndex.value = 0
 // Reset unsaved changes flag
 hasUnsavedChanges.value = false
 }
 catch (e: any) {
 error.value = e.message
 console.error(e)
 }
 finally {
 loading.value = false
 }
 }
 async function createWorkflow(data: Partial<Workflow>) {
 saving.value = true
 error.value = null
 try {
 const workflow = await client.post<Workflow>('/workflows/', data)
 workflows.value.unshift(workflow)
 return workflow
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 finally {
 saving.value = false
 }
 }
 async function saveWorkflow {
 if (!currentWorkflow.value)
 return
 saving.value = true
 error.value = null
 try {
 const workflow = await client.put<Workflow>(`/workflows/${currentWorkflow.value.id}/bulk-update/`, {
 nodes: toBackendNodes(nodes.value),
 edges: toBackendEdges(edges.value),
 delete_orphans: true,
 })
 currentWorkflow.value = workflow
 // Update nodes and edges with server IDs
 nodes.value = toVueFlowNodes(workflow.nodes || )
 edges.value = toVueFlowEdges(workflow.edges || )
 // Reset unsaved changes flag and clear draft
 hasUnsavedChanges.value = false
 clearDraft
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 finally {
 saving.value = false
 }
 }
 async function updateWorkflowSettings(settings: Partial<Workflow>) {
 if (!currentWorkflow.value)
 return
 saving.value = true
 error.value = null
 try {
 const workflow = await client.patch<Workflow>(`/workflows/${currentWorkflow.value.id}/`, settings)
 currentWorkflow.value = { ...currentWorkflow.value, ...workflow }
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 finally {
 saving.value = false
 }
 }
 async function deleteWorkflow(id: string) {
 try {
 await client.del(`/workflows/${id}/`)
 workflows.value = workflows.value.filter(w => w.id !== id)
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 }
 async function toggleWorkflowActive(id: string, isActive: boolean) {
 try {
 const workflow = await client.patch<Workflow>(`/workflows/${id}/`, { is_active: isActive })
 // Update in workflows list
 const index = workflows.value.findIndex(w => w.id === id)
 if (index !== -1) {
 workflows.value[index] = { ...workflows.value[index], ...workflow }
 }
 // Update current workflow if it's the same
 if (currentWorkflow.value?.id === id) {
 currentWorkflow.value = { ...currentWorkflow.value, ...workflow }
 }
 return workflow
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 }
 async function executeWorkflow(inputData: Record<string, any> = {}): Promise<ManualTriggerResponse | null> {
 if (!currentWorkflow.value)
 return null
 try {
 return await client.post<ManualTriggerResponse>(`/workflows/${currentWorkflow.value.id}/execute/`, { input_data: inputData })
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 }
 async function duplicateWorkflow(id: string, name?: string, projectId?: string) {
 try {
 const workflow = await client.post<Workflow>(`/workflows/${id}/duplicate/`, { name, project_id: projectId })
 workflows.value.unshift(workflow)
 return workflow
 }
 catch (e: any) {
 error.value = e.message
 throw e
 }
 }
 // Node operations
 function addNode(node: Node) {
 saveToHistory
 nodes.value.push(node)
 }
 function updateNode(nodeId: string, updates: Partial<Node>) {
 saveToHistory
 const index = nodes.value.findIndex(n => n.id === nodeId)
 if (index !== -1) {
 nodes.value[index] = { ...nodes.value[index], ...updates }
 }
 }
 function updateNodeData(nodeId: string, data: Record<string, any>) {
 saveToHistory
 const index = nodes.value.findIndex(n => n.id === nodeId)
 if (index !== -1) {
 nodes.value[index].data = { ...nodes.value[index].data, ...data }
 }
 }
 function removeNode(nodeId: string) {
 saveToHistory
 nodes.value = nodes.value.filter(n => n.id !== nodeId)
 // Also remove connected edges
 edges.value = edges.value.filter(e => e.source !== nodeId && e.target !== nodeId)
 }
 // Edge operations
 function addEdge(edge: Edge) {
 saveToHistory
 edges.value.push(edge)
 }
 function removeEdge(edgeId: string) {
 saveToHistory
 edges.value = edges.value.filter(e => e.id !== edgeId)
 }
 // Selection
 function selectNode(nodeId: string | null) {
 selectedNodeId.value = nodeId
 }
 // Draft management
 function getDraftKey: string | null {
 return currentWorkflow.value ? `${DRAFT_KEY_PREFIX}${currentWorkflow.value.id}`: null
 }
 function saveDraft {
 const key = getDraftKey
 if (!key)
 return
 const draft = {
 nodes: JSON.parse(JSON.stringify(nodes.value)),
 edges: JSON.parse(JSON.stringify(edges.value)),
 savedAt: new Date.toISOString,
 }
 localStorage.setItem(key, JSON.stringify(draft))
 }
 function loadDraft: boolean {
 const key = getDraftKey
 if (!key)
 return false
 const draftStr = localStorage.getItem(key)
 if (!draftStr)
 return false
 try {
 const draft = JSON.parse(draftStr)
 nodes.value = draft.nodes
 edges.value = draft.edges
 hasUnsavedChanges.value = true
 return true
 }
 catch {
 return false
 }
 }
 function clearDraft {
 const key = getDraftKey
 if (key) {
 localStorage.removeItem(key)
 }
 }
 function hasDraft: boolean {
 const key = getDraftKey
 if (!key)
 return false
 return localStorage.getItem(key) !== null
 }
 function getDraftInfo: { savedAt: string } | null {
 const key = getDraftKey
 if (!key)
 return null
 const draftStr = localStorage.getItem(key)
 if (!draftStr)
 return null
 try {
 const draft = JSON.parse(draftStr)
 return { savedAt: draft.savedAt }
 }
 catch {
 return null
 }
 }
 return {
 workflows,
 currentWorkflow,
 loading,
 saving,
 error,
 nodes,
 edges,
 selectedNodeId,
 selectedNode,
 canUndo,
 canRedo,
 hasUnsavedChanges,
 fetchWorkflows,
 fetchWorkflow,
 createWorkflow,
 saveWorkflow,
 updateWorkflowSettings,
 deleteWorkflow,
 toggleWorkflowActive,
 executeWorkflow,
 duplicateWorkflow,
 addNode,
 updateNode,
 updateNodeData,
 removeNode,
 addEdge,
 removeEdge,
 selectNode,
 saveToHistory,
 undo,
 redo,
 saveDraft,
 loadDraft,
 clearDraft,
 hasDraft,
 getDraftInfo,
 } as const
})
