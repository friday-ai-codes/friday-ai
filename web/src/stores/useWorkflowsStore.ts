import type { ManualTriggerResponse, WorkflowEdgeStore, WorkflowNodeStore } from '~/types'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import client from '~/api/client'
import { getDefaultConfig as getRegistryDefaultConfig } from '~/types/workflow/registry'
// Backend API response types (snake_case)
export interface WorkflowNode {
 id: string
 short_id: string
 node_type: string
 name: string
 description: string
 position_x: number
 position_y: number
 config: Record<string, unknown>
 timeout: number | null
 retry_count: number
 retry_delay: number
 run_condition: Record<string, unknown> | null
 metadata: Record<string, unknown>
 created_at: string
 updated_at: string
}
export interface WorkflowEdge {
 id: string
 source_node: string
 target_node: string
 source_handle: string
 target_handle: string
 condition: Record<string, unknown> | null
 label: string
 style: Record<string, unknown>
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
 trigger_config: Record<string, unknown>
 is_active: boolean
 is_template: boolean
 max_concurrent_executions: number
 default_timeout: number
 metadata: Record<string, unknown>
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
 // Undo/Redo history (uses store types, not X6 types)
 const history = ref<{ nodes: WorkflowNodeStore, edges: WorkflowEdgeStore }>
 const historyIndex = ref(-1)
 const maxHistorySize = 50
 // Store nodes and edges (X6-agnostic format)
 const nodes = ref<WorkflowNodeStore>
 const edges = ref<WorkflowEdgeStore>
 // Unsaved changes tracking
 const hasUnsavedChanges = ref(false)
 // Computed
 const canUndo = computed( => historyIndex.value > 0)
 const canRedo = computed( => historyIndex.value < history.value.length - 1)
 const selectedNode = computed(: WorkflowNodeStore | null => {
 if (!selectedNodeId.value)
 return null
 return nodes.value.find(n => n.id === selectedNodeId.value) || null
 })
 /**
 * Get node by ID
 */
 function getNodeById(nodeId: string): WorkflowNodeStore | undefined {
 return nodes.value.find(n => n.id === nodeId)
 }
 // ============================================================================
 // Type Converters: Backend API <-> Store Format
 // ============================================================================
 /**
 * Convert backend nodes to store format
 * Uses UUID as id for internal operations, shortId for display
 */
 function toStoreNodes(workflowNodes: WorkflowNode): WorkflowNodeStore {
 return workflowNodes.map(node => ({
 id: node.id,
 shortId: node.short_id,
 nodeType: node.node_type,
 name: node.name,
 description: node.description,
 position: { x: node.position_x, y: node.position_y },
 config: node.config,
 timeout: node.timeout,
 retryCount: node.retry_count,
 retryDelay: node.retry_delay,
 runCondition: node.run_condition,
 metadata: node.metadata,
 }))
 }
 /**
 * Convert backend edges to store format
 */
 function toStoreEdges(workflowEdges: WorkflowEdge): WorkflowEdgeStore {
 return workflowEdges.map(edge => ({
 id: edge.id,
 source: edge.source_node,
 sourcePort: edge.source_handle,
 target: edge.target_node,
 targetPort: edge.target_handle,
 label: edge.label,
 condition: edge.condition,
 }))
 }
 /**
 * Get default config for a node type (merged from registry and local defaults)
 */
 function getDefaultConfig(nodeType: string): Record<string, unknown> {
 // Start with registry defaults
 const registryDefaults = (getRegistryDefaultConfig(nodeType) ?? {}) as Record<string, unknown>
 // Additional local defaults for specific types
 const localDefaults: Record<string, Record<string, unknown>> = {
 ai_prompt: {
 user_prompt: '{{global.description}}',
 },
 fetch_work_item: {
 work_item_id: '{{input.work_item_id}}',
 },
 }
 return { ...registryDefaults, ...localDefaults[nodeType] }
 }
 /**
 * Convert store nodes back to backend format
 */
 function toBackendNodes(storeNodes: WorkflowNodeStore): Partial<WorkflowNode> {
 return storeNodes.map((node) => {
 const defaultConfig = getDefaultConfig(node.nodeType)
 // Merge default config with user config, user config takes priority
 const config = { ...defaultConfig, ...node.config }
 return {
 id: node.id,
 node_type: node.nodeType,
 name: node.name || 'Untitled',
 description: node.description || '',
 position_x: node.position.x,
 position_y: node.position.y,
 config,
 timeout: node.timeout,
 retry_count: node.retryCount,
 retry_delay: node.retryDelay,
 run_condition: node.runCondition,
 metadata: node.metadata,
 }
 })
 }
 /**
 * Convert store edges back to backend format
 */
 function toBackendEdges(storeEdges: WorkflowEdgeStore): Partial<WorkflowEdge> {
 return storeEdges.map(edge => ({
 source_node_id: edge.source,
 target_node_id: edge.target,
 source_handle: edge.sourcePort || 'default',
 target_handle: edge.targetPort || 'default',
 condition: edge.condition,
 label: edge.label || '',
 }))
 }
 // ============================================================================
 // X6 Sync Methods (called by useX6Sync composable)
 // ============================================================================
 /**
 * Mark workflow as dirty (has unsaved changes)
 */
 function markDirty {
 hasUnsavedChanges.value = true
 }
 /**
 * Called when the canvas moves a node (lightweight, no history snapshot)
 */
 function updateNodePosition(nodeId: string, position: { x: number, y: number }) {
 const node = nodes.value.find(n => n.id === nodeId)
 if (node) {
 node.position = position
 markDirty
 }
 }
 // ============================================================================
 // History Management
 // ============================================================================
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
 // ============================================================================
 // API Calls
 // ============================================================================
 async function fetchWorkflows(projectId?: string) {
 loading.value = true
 error.value = null
 try {
 const params: Record<string, string> = {}
 if (projectId)
 params.project_id = projectId
 const data = await client.get<{ results?: Workflow }>('/workflows/', params)
 workflows.value = (data.results || data) as Workflow
 return workflows.value
 }
 catch (e: unknown) {
 error.value = (e as Error).message
 return
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
 // Convert to store format
 nodes.value = toStoreNodes(workflow.nodes || )
 edges.value = toStoreEdges(workflow.edges || )
 // Initialize history
 history.value = [{ nodes: JSON.parse(JSON.stringify(nodes.value)), edges: JSON.parse(JSON.stringify(edges.value)) }]
 historyIndex.value = 0
 // Reset unsaved changes flag
 hasUnsavedChanges.value = false
 }
 catch (e: unknown) {
 error.value = (e as Error).message
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
 catch (e: unknown) {
 error.value = (e as Error).message
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
 nodes.value = toStoreNodes(workflow.nodes || )
 edges.value = toStoreEdges(workflow.edges || )
 // Reset unsaved changes flag and clear draft
 hasUnsavedChanges.value = false
 clearDraft
 }
 catch (e: unknown) {
 error.value = (e as Error).message
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
 catch (e: unknown) {
 error.value = (e as Error).message
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
 catch (e: unknown) {
 error.value = (e as Error).message
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
 catch (e: unknown) {
 error.value = (e as Error).message
 throw e
 }
 }
 async function executeWorkflow(inputData: Record<string, unknown> = {}): Promise<ManualTriggerResponse | null> {
 if (!currentWorkflow.value)
 return null
 try {
 return await client.post<ManualTriggerResponse>(`/workflows/${currentWorkflow.value.id}/execute/`, { input_data: inputData })
 }
 catch (e: unknown) {
 error.value = (e as Error).message
 throw e
 }
 }
 async function duplicateWorkflow(id: string, name?: string, projectId?: string) {
 try {
 const workflow = await client.post<Workflow>(`/workflows/${id}/duplicate/`, { name, project_id: projectId })
 workflows.value.unshift(workflow)
 return workflow
 }
 catch (e: unknown) {
 error.value = (e as Error).message
 throw e
 }
 }
 // ============================================================================
 // Node Operations (with history)
 // ============================================================================
 function addNode(node: WorkflowNodeStore) {
 saveToHistory
 nodes.value.push(node)
 }
 function updateNode(nodeId: string, updates: Partial<WorkflowNodeStore>) {
 saveToHistory
 const index = nodes.value.findIndex(n => n.id === nodeId)
 if (index !== -1) {
 nodes.value[index] = { ...nodes.value[index], ...updates }
 }
 }
 function updateNodeData(nodeId: string, data: { name?: string, description?: string, config?: Record<string, unknown> }) {
 saveToHistory
 const index = nodes.value.findIndex(n => n.id === nodeId)
 if (index !== -1) {
 const node = nodes.value[index]
 // Update name and description if provided
 if (data.name !== undefined) {
 node.name = data.name
 }
 if (data.description !== undefined) {
 node.description = data.description
 }
 // Merge config if provided
 if (data.config !== undefined) {
 node.config = { ...node.config, ...data.config }
 }
 }
 }
 function removeNode(nodeId: string) {
 saveToHistory
 nodes.value = nodes.value.filter(n => n.id !== nodeId)
 // Also remove connected edges
 edges.value = edges.value.filter(e => e.source !== nodeId && e.target !== nodeId)
 }
 // ============================================================================
 // Edge Operations (with history)
 // ============================================================================
 function addEdge(edge: WorkflowEdgeStore) {
 saveToHistory
 edges.value.push(edge)
 }
 function removeEdge(edgeId: string) {
 saveToHistory
 edges.value = edges.value.filter(e => e.id !== edgeId)
 }
 // ============================================================================
 // Selection
 // ============================================================================
 function selectNode(nodeId: string | null) {
 selectedNodeId.value = nodeId
 }
 // ============================================================================
 // Draft Management
 // ============================================================================
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
 // State
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
 // API
 fetchWorkflows,
 fetchWorkflow,
 createWorkflow,
 saveWorkflow,
 updateWorkflowSettings,
 deleteWorkflow,
 toggleWorkflowActive,
 executeWorkflow,
 duplicateWorkflow,
 // Node operations (with history)
 addNode,
 updateNode,
 updateNodeData,
 removeNode,
 // Edge operations (with history)
 addEdge,
 removeEdge,
 // Selection
 selectNode,
 // History
 saveToHistory,
 undo,
 redo,
 // Draft
 saveDraft,
 loadDraft,
 clearDraft,
 hasDraft,
 getDraftInfo,
 // Canvas position sync (lightweight, no history)
 markDirty,
 updateNodePosition,
 // Getters
 getNodeById,
 } as const
})
