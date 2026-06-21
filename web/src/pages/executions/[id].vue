<script setup lang="ts">
/**
 * 执行详情页 — 全屏 DAG 视图（编排入口组件）
 *
 * 布局：紧凑顶部栏 + 全屏 ExecutionDagView + 右侧 NodeDetailSheet。
 * 节点状态通过 WebSocket 实时更新，执行完成后自动加载 Timeline 瓶颈数据。
 */
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { computed, ref, watch } from 'vue'
import { useExecutionReplay } from '~/components/execution/dag/composables/useExecutionReplay'
import NodeDetailSheet from '~/components/execution/NodeDetailSheet.vue'
import ReplayControls from '~/components/execution/replay/ReplayControls.vue'
import ReplayTimeline from '~/components/execution/replay/ReplayTimeline.vue'
import ExecutionContent from './components/ExecutionContent.vue'
import ExecutionDialogs from './components/ExecutionDialogs.vue'
import ExecutionHeader from './components/ExecutionHeader.vue'
import ExecutionStatusBanners from './components/ExecutionStatusBanners.vue'
import { useDebugMode } from './composables/useDebugMode'
import { useExecutionControls } from './composables/useExecutionControls'
import { useExecutionState } from './composables/useExecutionState'
import { useResumeLogic } from './composables/useResumeLogic'

// ----- 抽屉状态 -----
const sheetOpen = ref(false)
const selectedNodeExecution = ref<NodeExecution | null>(null)
const selectedNodeId = ref<string | null>(null)
const hasAutoOpenedWaitingApproval = ref(false)

// ----- Composables -----
const {
  executionId,
  currentExecution,
  timelineData,
  loading,
  error,
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
} = useExecutionState()

const {
  isPausing,
  isResuming,
  isCancelling,
  isRetrying,
  approvalDialogOpen,
  approvalComment,
  approving,
  triggerDialogOpen,
  triggerInputData,
  triggering,
  handlePause,
  handleResume,
  handleCancel,
  handleRetry,
  handleApprove,
  handleReject,
  handleTrigger,
} = useExecutionControls(executionId, store, selectedNodeExecution)

const {
  breakpoints,
  isBreakpointMode,
  handleToggleBreakpoint,
  handleDebugRelease,
  handleDebugSkip,
  handleCancelDebug,
} = useDebugMode(executionId, store, currentExecution)

const {
  resumeDialogOpen,
  resumeNodeName,
  resuming,
  resumeSkipNodes,
  resumeRerunNodes,
  resumePreviewLoading,
  handleResumeClick,
  handleResumeFromFailed,
} = useResumeLogic(executionId, currentExecution, definitionChanged, router)

// ----- 计算属性（需要跨 composable 的数据） -----
/** : 选中节点是否处于调试暂停状态 */
const isSelectedNodeDebugPaused = computed(() =>
  currentExecution.value?.is_debug === true
  && currentExecution.value?.debug_paused_at_node != null
  && currentExecution.value?.debug_paused_at_node === selectedNodeId.value,
)

/** 选中节点的配置（从 workflow_definition 中查找） */
const selectedNodeConfig = computed<Record<string, unknown>>(() => {
  if (!selectedNodeId.value || !currentExecution.value?.workflow_definition)
    return {}
  const defNode = currentExecution.value.workflow_definition.nodes.find(
    n => n.id === selectedNodeId.value,
  )
  return defNode?.config ?? {}
})

/**
 * UX-02 D-09：选中节点的 Provider 快照
 *  - undefined: 非 AI 节点（不渲染 ExecutionProviderSnapshot）
 *  - null:      AI 节点但历史 Execution miss（渲染 "未快照" 降级态）
 *  - NodeSnapshot: AI 节点命中快照
 */
const AI_NODE_TYPES_WEB = new Set([
  'ai_prompt',
  'ai_variable_extractor',
  'ai_plan_generation',
  'ai_coding',
  'ai_coding_dispatcher',
])
const selectedProviderSnapshot = computed(() => {
  if (!selectedNodeExecution.value || !selectedNodeId.value)
    return undefined
  const nodeType = selectedNodeExecution.value.node_type ?? ''
  if (!AI_NODE_TYPES_WEB.has(nodeType))
    return undefined
  const snapshots = (currentExecution.value?.context as any)?.node_snapshots ?? {}
  return snapshots[selectedNodeId.value] ?? null
})

/** UX-02 D-09：Replay 可用性——execution 处于终态才允许 */
const canReplaySnapshot = computed(() => {
  const status = currentExecution.value?.status
  return status === 'completed' || status === 'failed' || status === 'error' || status === 'cancelled'
})

/** UX-02 D-09：基于快照重放 handler（委托 useExecutionControls.handleRetry） */
function handleReplaySnapshot(_nodeId: string) {
  handleRetry()
}

/** 选中节点的瓶颈信息 */
const selectedBottleneckInfo = computed(() => {
  if (!selectedNodeExecution.value || !timelineData.value)
    return null
  const tlNode = timelineData.value.nodes.find(
    n => n.node_id === selectedNodeExecution.value!.node,
  )
  if (!tlNode?.is_bottleneck)
    return null

  const bottleneckNodes = timelineData.value.nodes
    .filter(n => n.is_bottleneck)
    .sort((a, b) => (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0))
  const rank = bottleneckNodes.findIndex(n => n.node_id === tlNode.node_id) + 1

  const percent = timelineData.value.summary.total_duration_seconds
    ? Math.round(((tlNode.duration_seconds ?? 0) / timelineData.value.summary.total_duration_seconds) * 100)
    : 0

  return {
    level: tlNode.bottleneck_level ?? 'warning',
    rank,
    durationPercent: percent,
  }
})

// ----- : 回放模式 -----
const isReplayMode = ref(false)

/** 终态执行才可回放 */
const canReplay = computed(() => {
  const status = currentExecution.value?.status
  return status === 'completed' || status === 'failed' || status === 'error' || status === 'cancelled'
})

const replay = useExecutionReplay(currentExecution)

/** 切换回放模式 */
function handleToggleReplay() {
  if (isReplayMode.value) {
    // 退出回放
    isReplayMode.value = false
    replay.reset()
    // 恢复 WebSocket
    store.connectWebSocket(executionId.value)
  }
  else {
    // 进入回放
    isReplayMode.value = true
    // 断开 WebSocket，避免实时更新干扰回放
    store.disconnectWebSocket?.()
    replay.reset()
  }
}

/** 步进控制能力 */
const canStepForward = computed(() => replay.currentTime.value < replay.totalDuration.value)
const canStepBackward = computed(() => replay.currentTime.value > 0)

// ----- 节点点击 -----
function handleNodeClick(nodeExecution: NodeExecution | null, nodeId: string) {
  selectedNodeExecution.value = nodeExecution
  selectedNodeId.value = nodeId
  sheetOpen.value = true
}

watch(executionId, () => {
  hasAutoOpenedWaitingApproval.value = false
})

watch(currentExecution, (execution) => {
  if (!execution || sheetOpen.value || hasAutoOpenedWaitingApproval.value)
    return

  const waitingApproval = execution.node_executions?.find(
    node => node.node_type === 'human_approval' && node.status === 'waiting_approval',
  )
  if (!waitingApproval)
    return

  selectedNodeExecution.value = waitingApproval
  selectedNodeId.value = waitingApproval.node
  sheetOpen.value = true
  hasAutoOpenedWaitingApproval.value = true
}, { immediate: true })

/** 抽屉内操作完成后刷新数据 */
function handleActionComplete() {
  store.fetchExecution(executionId.value)
}
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden">
    <ExecutionHeader
      :workflow-name="currentExecution?.workflow_name || ''"
      :execution-id="executionId"
      :status="currentExecution?.status"
      :progress="progress"
      :duration="duration"
      :trigger-log-id="currentExecution?.trigger_log_id"
      :retry-from-id="retryFromId"
      :resumed-from-id="resumedFromId"
      :is-pausing="isPausing"
      :is-resuming="isResuming"
      :is-cancelling="isCancelling"
      :is-retrying="isRetrying"
      :can-replay="canReplay"
      :is-replay-mode="isReplayMode"
      @pause="handlePause"
      @resume="handleResume"
      @cancel="handleCancel"
      @retry="handleRetry"
      @replay="handleToggleReplay"
      @refresh="store.fetchExecution(executionId)"
      @back="router.push('/executions')"
    />

    <ExecutionStatusBanners
      :ws-disconnected="wsDisconnected"
      :is-debug-execution="isDebugExecution"
      :is-active-status="isActiveStatus(currentExecution?.status)"
      :is-breakpoint-mode="isBreakpointMode"
      :debug-paused-node-name="debugPausedNodeName"
      @reconnect-ws="store.connectWebSocket(executionId)"
      @cancel-debug="handleCancelDebug"
      @update:is-breakpoint-mode="isBreakpointMode = $event"
    />

    <ExecutionContent
      :loading="loading"
      :error="error"
      :current-execution="currentExecution"
      :cost-data="costData"
      :cost-loading="costLoading"
      :timeline-data="timelineData"
      :definition-changed="definitionChanged"
      :breakpoints="breakpoints"
      :is-debug-execution="isDebugExecution"
      :is-pre-execution-failure="isPreExecutionFailure"
      :is-terminal-status="isTerminalStatus(currentExecution?.status)"
      :is-replay-mode="isReplayMode"
      :get-node-status="replay.getNodeStatus"
      @node-click="handleNodeClick"
      @resume-click="handleResumeClick"
      @debug-release="handleDebugRelease"
      @debug-skip="handleDebugSkip"
      @toggle-breakpoint="handleToggleBreakpoint"
      @retry="handleRetry"
    />

    <!-- : 回放控制面板 -->
    <Transition
      enter-active-class="transition ease-out duration-300"
      enter-from-class="translate-y-full opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition ease-in duration-200"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="translate-y-full opacity-0"
    >
      <div
        v-if="isReplayMode"
        class="shrink-0 bg-white/80 backdrop-blur-md border-t border-border/50 shadow-lg z-30"
      >
        <ReplayControls
          :is-playing="replay.isPlaying.value"
          :speed="replay.speed.value"
          :can-step-forward="canStepForward"
          :can-step-backward="canStepBackward"
          @play="replay.play"
          @pause="replay.pause"
          @step-forward="replay.stepForward"
          @step-backward="replay.stepBackward"
          @speed-change="replay.setSpeed"
        />
        <ReplayTimeline
          :current-time="replay.currentTime.value"
          :total-duration="replay.totalDuration.value"
          :node-executions="currentExecution?.node_executions ?? []"
          @seek="replay.seek"
        />
      </div>
    </Transition>

    <!-- 节点详情抽屉 -->
    <NodeDetailSheet
      :open="sheetOpen"
      :node-execution="selectedNodeExecution"
      :node-config="selectedNodeConfig"
      :bottleneck-info="selectedBottleneckInfo"
      :execution-id="executionId"
      :can-resume="!definitionChanged && (selectedNodeExecution?.status === 'failed')"
      :is-debug-paused="isSelectedNodeDebugPaused"
      :workflow-definition="currentExecution?.workflow_definition"
      :provider-snapshot="selectedProviderSnapshot"
      :can-replay-snapshot="canReplaySnapshot"
      @update:open="sheetOpen = $event"
      @action-complete="handleActionComplete"
      @resume-from-node="handleResumeClick"
      @replay-snapshot="handleReplaySnapshot"
    />

    <ExecutionDialogs
      :approval-dialog-open="approvalDialogOpen"
      :approval-comment="approvalComment"
      :approving="approving"
      :selected-node-execution="selectedNodeExecution"
      :trigger-dialog-open="triggerDialogOpen"
      :trigger-input-data="triggerInputData"
      :triggering="triggering"
      :resume-dialog-open="resumeDialogOpen"
      :resume-node-name="resumeNodeName"
      :resume-preview-loading="resumePreviewLoading"
      :resume-skip-nodes="resumeSkipNodes"
      :resume-rerun-nodes="resumeRerunNodes"
      :resuming="resuming"
      @update:approval-dialog-open="approvalDialogOpen = $event"
      @update:approval-comment="approvalComment = $event"
      @update:trigger-dialog-open="triggerDialogOpen = $event"
      @update:trigger-input-data="triggerInputData = $event"
      @update:resume-dialog-open="resumeDialogOpen = $event"
      @approve="handleApprove"
      @reject="handleReject"
      @trigger="handleTrigger"
      @resume-from-failed="handleResumeFromFailed"
    />
  </div>
</template>
