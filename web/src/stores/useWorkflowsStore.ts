import type { BackendValidationResult } from '~/stores/useWorkflowValidationStore'
import type { ManualTriggerResponse, WorkflowEdgeStore, WorkflowNodeStore } from '~/types'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import client, { ApiError } from '~/api/client'
import { migratePortId } from '~/components/workflow/editor/utils/portConfig'
import { useWorkflowValidationStore } from '~/stores/useWorkflowValidationStore'
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
  on_error: 'abort' | 'retry' | 'ignore'
  retry_times: number
  retry_delay: number
  node_timeout_seconds: number | null
  fallback_values: Record<string, unknown> | null
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
  // TRIG-02: 移除 'schedule' 假触发类型（前端不再支持定时触发，用户无法配出不生效触发器）
  trigger_type: 'manual' | 'webhook' | 'event'
  trigger_config: Record<string, unknown>
  is_active: boolean
  is_template: boolean
  max_concurrent_executions: number
  default_timeout: number
  metadata: Record<string, unknown>
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  execution_count: number
  last_execution: { id: string, status: string, created_at: string } | null
  created_at: string
  updated_at: string
}

const DRAFT_KEY_PREFIX = 'friday-workflow-draft-'

export const useWorkflowsStore = defineStore('workflows', () => {
  const workflows = ref<Workflow[]>([])
  const currentWorkflow = ref<Workflow | null>(null)
  /** 列表加载状态（仅 fetchWorkflows 使用，供列表页骨架屏） */
  const loading = ref(false)
  /**
   * 详情加载状态（fetchWorkflow 使用）。
   * 与列表 loading 分离：避免在列表页上点"执行"等操作拉取详情时，
   * 列表瞬间切回骨架屏造成页面抖动。
   */
  const detailLoading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)

  // Selected node for configuration panel
  const selectedNodeId = ref<string | null>(null)

  // Undo/Redo history (uses store types, not X6 types)
  const history = ref<{ nodes: WorkflowNodeStore[], edges: WorkflowEdgeStore[] }[]>([])
  const historyIndex = ref(-1)
  const maxHistorySize = 50

  // Store nodes and edges (X6-agnostic format)
  const nodes = ref<WorkflowNodeStore[]>([])
  const edges = ref<WorkflowEdgeStore[]>([])

  // Unsaved changes tracking
  const hasUnsavedChanges = ref(false)

  // Dirty node tracking — 记录配置已修改但未保存的节点 ID
  const dirtyNodeIds = ref<Set<string>>(new Set())

  // Computed
  const canUndo = computed(() => historyIndex.value > 0)
  const canRedo = computed(() => historyIndex.value < history.value.length - 1)

  const selectedNode = computed((): WorkflowNodeStore | null => {
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
  function toStoreNodes(workflowNodes: WorkflowNode[]): WorkflowNodeStore[] {
    return workflowNodes.map(node => ({
      id: node.id,
      shortId: node.short_id,
      nodeType: node.node_type,
      name: node.name,
      description: node.description,
      position: { x: node.position_x, y: node.position_y },
      config: node.config,
      onError: node.on_error ?? 'abort',
      retryTimes: node.retry_times ?? 0,
      retryDelay: node.retry_delay ?? 5,
      nodeTimeoutSeconds: node.node_timeout_seconds ?? null,
      fallbackValues: node.fallback_values ?? null,
      runCondition: node.run_condition,
      metadata: node.metadata,
    }))
  }

  /**
   * Convert backend edges to store format.
   * Normalizes old indexed port IDs (e.g. "output-0") to semantic names
   * (e.g. "default", "approved") for backward compatibility.
   *
   * migratePortId 使用 portConfig 的静态端口回退表（非 store），故端口顺序
   * 在 store 未就绪时也稳定；且 [id].vue 已顺序化 await fetchNodeTypes() 先于
   * fetchWorkflow()（RESEARCH Pitfall 4），存量 edge 不会退化为 default。
   */
  function toStoreEdges(workflowEdges: WorkflowEdge[], workflowNodes: WorkflowNode[]): WorkflowEdgeStore[] {
    const nodeTypeMap = new Map(workflowNodes.map(n => [n.id, n.node_type]))

    return workflowEdges.map(edge => ({
      id: edge.id,
      source: edge.source_node,
      sourcePort: migratePortId(edge.source_handle, nodeTypeMap.get(edge.source_node), 'output'),
      target: edge.target_node,
      targetPort: migratePortId(edge.target_handle, nodeTypeMap.get(edge.target_node), 'input'),
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
  function toBackendNodes(storeNodes: WorkflowNodeStore[]): Partial<WorkflowNode>[] {
    return storeNodes.map((node) => {
      const defaultConfig = getDefaultConfig(node.nodeType)
      // Merge default config with user config, user config takes priority
      const config = { ...defaultConfig, ...node.config }

      return {
        id: node.id,
        // VAR-01 前端半边：客户端权威 short_id 上送，服务端校验唯一性后落库
        short_id: node.shortId,
        node_type: node.nodeType,
        name: node.name || 'Untitled',
        description: node.description || '',
        position_x: node.position.x,
        position_y: node.position.y,
        config,
        on_error: node.onError,
        retry_times: node.retryTimes,
        retry_delay: node.retryDelay,
        node_timeout_seconds: node.nodeTimeoutSeconds,
        fallback_values: node.fallbackValues,
        run_condition: node.runCondition,
        metadata: node.metadata,
      }
    })
  }

  /**
   * Convert store edges back to backend format
   */
  function toBackendEdges(storeEdges: WorkflowEdgeStore[]): Partial<WorkflowEdge>[] {
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
  function markDirty() {
    hasUnsavedChanges.value = true
  }

  /**
   * Called when the canvas moves a node (lightweight, no history snapshot)
   */
  function updateNodePosition(nodeId: string, position: { x: number, y: number }) {
    const node = nodes.value.find(n => n.id === nodeId)
    if (node) {
      node.position = position
      markDirty()
    }
  }

  // ============================================================================
  // History Management
  // ============================================================================

  /**
   * Save CURRENT state to history (call AFTER mutation, not before).
   * fetchWorkflow seeds the initial state, so the first call after a
   * mutation creates a correct redo-able snapshot.
   */
  function saveToHistory() {
    // Remove any redo history
    if (historyIndex.value < history.value.length - 1) {
      history.value = history.value.slice(0, historyIndex.value + 1)
    }

    // Add current state (post-mutation)
    history.value.push({
      nodes: JSON.parse(JSON.stringify(nodes.value)),
      edges: JSON.parse(JSON.stringify(edges.value)),
    })

    // Limit history size
    if (history.value.length > maxHistorySize) {
      history.value.shift()
    }

    historyIndex.value++

    // Mark as having unsaved changes
    hasUnsavedChanges.value = true
  }

  function undo() {
    if (!canUndo.value)
      return

    historyIndex.value--
    const state = history.value[historyIndex.value]
    nodes.value = JSON.parse(JSON.stringify(state.nodes))
    edges.value = JSON.parse(JSON.stringify(state.edges))
  }

  function redo() {
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

  async function fetchWorkflows(spaceId?: string) {
    loading.value = true
    error.value = null
    try {
      const params: Record<string, string> = {}
      if (spaceId)
        params.space_id = spaceId

      const data = await client.get<{ results?: Workflow[] }>('/workflows/', params)
      workflows.value = (data.results || data) as Workflow[]
      return workflows.value
    }
    catch (e: unknown) {
      error.value = (e as Error).message
      return []
    }
    finally {
      loading.value = false
    }
  }

  async function fetchWorkflow(id: string) {
    detailLoading.value = true
    error.value = null
    try {
      const workflow = await client.get<Workflow>(`/workflows/${id}/`)
      currentWorkflow.value = workflow

      // Convert to store format
      const apiNodes = workflow.nodes || []
      nodes.value = toStoreNodes(apiNodes)
      edges.value = toStoreEdges(workflow.edges || [], apiNodes)

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
      detailLoading.value = false
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

  async function saveWorkflow() {
    if (!currentWorkflow.value)
      return

    const validationStore = useWorkflowValidationStore()
    // 每次保存重置上一轮校验问题，避免陈旧问题残留面板
    validationStore.clearAllIssues()

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
      const savedNodes = workflow.nodes || []
      nodes.value = toStoreNodes(savedNodes)
      edges.value = toStoreEdges(workflow.edges || [], savedNodes)

      // Reset unsaved changes flag and clear draft
      hasUnsavedChanges.value = false
      dirtyNodeIds.value = new Set()
      clearDraft()
    }
    catch (e: unknown) {
      // 后端 WorkflowGraphValidator 拒绝非法图时返回 400 + {errors,warnings}
      // （与 20-02 dry-run 同源）。灌入 validation store 由 IssuesPanel 呈现，
      // 并保持抛出——错误阻断保存。
      if (e instanceof ApiError && e.status === 400) {
        const body = e.body as BackendValidationResult | null
        if (body && (body.errors?.length || body.warnings?.length)) {
          validationStore.addIssues(body)
        }
      }
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

  async function executeWorkflow(inputData: Record<string, unknown> = {}, debugMode: boolean = false, stopBeforeNodeId?: string): Promise<ManualTriggerResponse | null> {
    if (!currentWorkflow.value)
      return null

    try {
      const payload: Record<string, unknown> = {
        input_data: inputData,
        debug_mode: debugMode,
      }
      if (stopBeforeNodeId) {
        payload.stop_before_node_id = stopBeforeNodeId
      }
      return await client.post<ManualTriggerResponse>(`/workflows/${currentWorkflow.value.id}/execute/`, payload)
    }
    catch (e: unknown) {
      error.value = (e as Error).message
      throw e
    }
  }

  async function duplicateWorkflow(id: string, name?: string, spaceId?: string) {
    try {
      const workflow = await client.post<Workflow>(`/workflows/${id}/duplicate/`, { name, space_id: spaceId })
      workflows.value.unshift(workflow)
      return workflow
    }
    catch (e: unknown) {
      error.value = (e as Error).message
      throw e
    }
  }

  /**
   * Export current workflow as JSON file download
   */
  function exportWorkflowJSON(): boolean {
    const wf = currentWorkflow.value
    if (!wf) {
      return false
    }

    const exportData = {
      name: wf.name,
      description: wf.description,
      icon: wf.icon,
      trigger_type: wf.trigger_type,
      trigger_config: wf.trigger_config,
      nodes: wf.nodes.map(node => ({
        id: node.id,
        short_id: node.short_id,
        node_type: node.node_type,
        name: node.name,
        description: node.description,
        position_x: node.position_x,
        position_y: node.position_y,
        config: node.config,
        on_error: node.on_error,
        retry_times: node.retry_times,
        retry_delay: node.retry_delay,
        node_timeout_seconds: node.node_timeout_seconds,
        fallback_values: node.fallback_values,
        run_condition: node.run_condition,
        metadata: node.metadata,
      })),
      edges: wf.edges.map(edge => ({
        id: edge.id,
        source_node: edge.source_node,
        target_node: edge.target_node,
        source_handle: edge.source_handle,
        target_handle: edge.target_handle,
        condition: edge.condition,
        label: edge.label,
        style: edge.style,
      })),
      exported_at: new Date().toISOString(),
      friday_version: (typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.1.0'),
    }

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)

    const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    const fileName = `${wf.name || 'workflow'}-${dateStr}.json`

    const a = document.createElement('a')
    a.href = url
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    return true
  }

  // ============================================================================
  // Node Operations (with history)
  // ============================================================================

  function addNode(node: WorkflowNodeStore) {
    nodes.value.push(node)
    saveToHistory()
  }

  function updateNode(nodeId: string, updates: Partial<WorkflowNodeStore>) {
    const index = nodes.value.findIndex(n => n.id === nodeId)
    if (index !== -1) {
      nodes.value[index] = { ...nodes.value[index], ...updates }
    }
    saveToHistory()
  }

  function updateNodeData(nodeId: string, data: { name?: string, description?: string, config?: Record<string, unknown> }) {
    const next = new Set(dirtyNodeIds.value)
    next.add(nodeId)
    dirtyNodeIds.value = next
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
    saveToHistory()
  }

  /**
   * 取某父节点的全部附着子节点（SLOT-04）。
   * 子节点经 `metadata.parentNodeId === parentId` 标记，供 UI 取附着数/徽标。
   */
  function getChildNodes(parentId: string): WorkflowNodeStore[] {
    return nodes.value.filter(n => n.metadata?.parentNodeId === parentId)
  }

  /**
   * 把子节点附着到父节点（SLOT-04 单一入口）。
   * 写 `metadata.parentNodeId=parentId` 持久化父子关系（经既有 metadata JSON 列，
   * 无后端 schema 变更），并把位置改为相对父的坐标（由调用方 93-06 换算）。
   */
  function attachChild(childId: string, parentId: string, relativePosition: { x: number, y: number }) {
    const node = nodes.value.find(n => n.id === childId)
    if (!node)
      return
    node.metadata = { ...node.metadata, parentNodeId: parentId }
    node.position = relativePosition
    saveToHistory()
  }

  /**
   * 设置附着插件订阅的宿主信号（SLOT P4 信号反应器）。
   * 把已选信号写入 `metadata.subscribeSignals`（经既有 metadata JSON 列，无后端 schema
   * 变更）；保存工作流时由后端 config_sync 转换为 WorkflowReaction（reaction 配置为 SSOT）。
   */
  function setSubscribeSignals(childId: string, signals: string[]) {
    const node = nodes.value.find(n => n.id === childId)
    if (!node)
      return
    node.metadata = { ...node.metadata, subscribeSignals: signals }
    saveToHistory()
  }

  /**
   * 解除子节点附着（SLOT-04 单一入口）。
   * 清除 `metadata.parentNodeId`（delete 键，往返不残留）并恢复绝对坐标。
   */
  function detachChild(childId: string, absolutePosition: { x: number, y: number }) {
    const node = nodes.value.find(n => n.id === childId)
    if (!node)
      return
    const { parentNodeId: _drop, ...rest } = (node.metadata ?? {}) as Record<string, unknown>
    node.metadata = rest
    node.position = absolutePosition
    saveToHistory()
  }

  function removeNode(nodeId: string) {
    // SLOT-04 生命周期绑定：删父方案节点时级联删除其附着子节点（连同两者相关边）。
    // 先收集待删 id 集合再统一过滤，避免遍历中改数组。删普通节点（无子）退化为只删自身 + 连边。
    const childIds = nodes.value
      .filter(n => n.metadata?.parentNodeId === nodeId)
      .map(n => n.id)
    const removeIds = new Set<string>([nodeId, ...childIds])

    nodes.value = nodes.value.filter(n => !removeIds.has(n.id))
    // Also remove connected edges (含被级联删除子节点的连边)
    edges.value = edges.value.filter(e => !removeIds.has(e.source) && !removeIds.has(e.target))
    saveToHistory()
  }

  // ============================================================================
  // Edge Operations (with history)
  // ============================================================================

  function addEdge(edge: WorkflowEdgeStore) {
    edges.value.push(edge)
    saveToHistory()
  }

  function removeEdge(edgeId: string) {
    edges.value = edges.value.filter(e => e.id !== edgeId)
    saveToHistory()
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

  function getDraftKey(): string | null {
    return currentWorkflow.value ? `${DRAFT_KEY_PREFIX}${currentWorkflow.value.id}` : null
  }

  function saveDraft() {
    const key = getDraftKey()
    if (!key)
      return

    const draft = {
      nodes: JSON.parse(JSON.stringify(nodes.value)),
      edges: JSON.parse(JSON.stringify(edges.value)),
      savedAt: new Date().toISOString(),
    }
    localStorage.setItem(key, JSON.stringify(draft))
  }

  function loadDraft(): boolean {
    const key = getDraftKey()
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

  function clearDraft() {
    const key = getDraftKey()
    if (key) {
      localStorage.removeItem(key)
    }
  }

  function hasDraft(): boolean {
    const key = getDraftKey()
    if (!key)
      return false
    return localStorage.getItem(key) !== null
  }

  function getDraftInfo(): { savedAt: string } | null {
    const key = getDraftKey()
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
    detailLoading,
    saving,
    error,
    nodes,
    edges,
    selectedNodeId,
    selectedNode,
    canUndo,
    canRedo,
    hasUnsavedChanges,
    dirtyNodeIds,

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
    exportWorkflowJSON,

    // Node operations (with history)
    addNode,
    updateNode,
    updateNodeData,
    removeNode,

    // Parent/child attachment (SLOT-04, with history)
    attachChild,
    detachChild,
    getChildNodes,
    setSubscribeSignals,

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
