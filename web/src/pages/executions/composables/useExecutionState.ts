import type { TimelineData, WorkflowExecution } from '~/stores/useExecutionsStore'
import type { CostBreakdown } from '~/types/execution'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { checkWorkflowChanged, getCostBreakdown } from '~/api/workflow'
import { useExecutionsStore } from '~/stores/useExecutionsStore'

/** 活跃状态判断 */
function isActiveStatus(status?: string) {
  return ['running', 'pending', 'queued', 'paused', 'waiting_approval', 'waiting_event', 'suspended'].includes(status || '')
}

/** 执行是否已结束（用于触发 Timeline 加载） */
function isTerminalStatus(status?: string) {
  return ['completed', 'failed', 'cancelled', 'timeout'].includes(status || '')
}

export function useExecutionState() {
  const route = useRoute()
  const router = useRouter()
  const executionId = computed(() => (route.params as { id: string }).id)

  const store = useExecutionsStore()
  const { currentExecution, timelineData, loading, error, wsStatus } = storeToRefs(store)

  // ----- 成本数据 -----
  const costData = ref<CostBreakdown | null>(null)
  const costLoading = ref(false)

  async function fetchCostData() {
    costLoading.value = true
    try {
      costData.value = await getCostBreakdown(executionId.value)
    }
    catch {
      costData.value = null
    }
    finally {
      costLoading.value = false
    }
  }

  // ----- 变更检测 -----
  const definitionChanged = ref(false)

  async function fetchDefinitionChanged() {
    if (!isTerminalStatus(currentExecution.value?.status)) {
      definitionChanged.value = false
      return
    }
    try {
      const result = await checkWorkflowChanged(executionId.value)
      definitionChanged.value = result.changed
    }
    catch {
      definitionChanged.value = false
    }
  }

  // ----- 计算属性 -----
  /** : 是否为调试执行 */
  const isDebugExecution = computed(() => currentExecution.value?.is_debug === true)

  /** : 当前调试暂停节点名称 */
  const debugPausedNodeName = computed(() => {
    const nodeId = currentExecution.value?.debug_paused_at_node
    if (!nodeId || !currentExecution.value?.workflow_definition)
      return null
    const defNode = currentExecution.value.workflow_definition.nodes.find(n => n.id === nodeId)
    return defNode?.name ?? nodeId
  })

  /** WebSocket 断线检测 */
  const wsDisconnected = computed(() => {
    if (!currentExecution.value)
      return false
    if (!isActiveStatus(currentExecution.value.status))
      return false
    return wsStatus.value === 'CLOSED'
  })

  /** 预执行失败：执行在节点运行前就失败 */
  const isPreExecutionFailure = computed(() => {
    const exec = currentExecution.value
    if (!exec)
      return false
    return exec.status === 'failed'
      && exec.total_nodes === 0
      && exec.completed_nodes === 0
      && exec.failed_nodes === 0
      && !!exec.error_message
  })

  const progress = computed(() => currentExecution.value?.progress || 0)

  const duration = computed(() => {
    if (!currentExecution.value?.duration)
      return '-'
    const seconds = Math.round(currentExecution.value.duration)
    if (seconds < 60)
      return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  })

  /** 检测是否为重试执行，提取原始执行 ID */
  const retryFromId = computed(() => {
    const metadata = currentExecution.value?.trigger_data?.metadata
    return metadata?.retry_from || null
  })

  /** 检测是否为「从此继续」执行，提取原始执行 ID */
  const resumedFromId = computed(() => {
    return currentExecution.value?.resumed_from || null
  })

  // ----- 生命周期 -----
  onMounted(async () => {
    await store.fetchExecution(executionId.value)
    if (isActiveStatus(currentExecution.value?.status)) {
      store.connectWebSocket(executionId.value)
    }
    if (isTerminalStatus(currentExecution.value?.status)) {
      store.fetchTimeline(executionId.value)
    }
    fetchCostData()
    fetchDefinitionChanged()
  })

  onUnmounted(() => {
    store.disconnectWebSocket()
  })

  // 监听状态变化：连接/断开 WS + 加载 Timeline
  watch(() => currentExecution.value?.status, (newStatus, oldStatus) => {
    if (isActiveStatus(newStatus) && !isActiveStatus(oldStatus)) {
      store.connectWebSocket(executionId.value)
    }
    else if (!isActiveStatus(newStatus) && isActiveStatus(oldStatus)) {
      store.disconnectWebSocket()
    }
    if (isTerminalStatus(newStatus) && !isTerminalStatus(oldStatus)) {
      store.fetchTimeline(executionId.value)
      if (!costData.value)
        fetchCostData()
    }
  })

  return {
    executionId,
    currentExecution: currentExecution as import('vue').Ref<WorkflowExecution | null>,
    timelineData: timelineData as import('vue').Ref<TimelineData | null>,
    loading,
    error,
    wsStatus,
    router,
    store,
    costData,
    costLoading,
    definitionChanged,
    isDebugExecution,
    debugPausedNodeName,
    wsDisconnected,
    isPreExecutionFailure,
    progress,
    duration,
    retryFromId,
    resumedFromId,
    isActiveStatus,
    isTerminalStatus,
  }
}
