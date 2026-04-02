<script setup lang="ts">
/**
 * 执行详情页 — 全屏 DAG 视图（编排入口组件）
 *
 * 布局：紧凑顶部栏 + 全屏 ExecutionDagView + 右侧 NodeDetailSheet。
 * 节点状态通过 WebSocket 实时更新，执行完成后自动加载 Timeline 瓶颈数据。
 */
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { computed, ref } from 'vue'
import NodeDetailSheet from '~/components/execution/NodeDetailSheet.vue'
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
} = useExecutionState
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
/** Phase: 选中节点是否处于调试暂停状态 */
const isSelectedNodeDebugPaused = computed( =>
 currentExecution.value?.is_debug === true
 && currentExecution.value?.debug_paused_at_node != null
 && currentExecution.value?.debug_paused_at_node === selectedNodeId.value,
)
/** 选中节点的配置（从 workflow_definition 中查找） */
const selectedNodeConfig = computed<Record<string, unknown>>( => {
 if (!selectedNodeId.value || !currentExecution.value?.workflow_definition)
 return {}
 const defNode = currentExecution.value.workflow_definition.nodes.find(
 n => n.id === selectedNodeId.value,
 )
 return defNode?.config ?? {}
})
/** 选中节点的瓶颈信息 */
const selectedBottleneckInfo = computed( => {
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
 ? Math.round(((tlNode.duration_seconds ?? 0) / timelineData.value.summary.total_duration_seconds) * 100): 0
 return {
 level: tlNode.bottleneck_level ?? 'warning',
 rank,
 durationPercent: percent,
 }
})
// ----- 节点点击 -----
function handleNodeClick(nodeExecution: NodeExecution | null, nodeId: string) {
 selectedNodeExecution.value = nodeExecution
 selectedNodeId.value = nodeId
 sheetOpen.value = true
}
/** 抽屉内操作完成后刷新数据 */
function handleActionComplete {
 store.fetchExecution(executionId.value)
}
</script>
<template>
 <div class="h-screen flex flex-col overflow-hidden">
 <ExecutionHeader:workflow-name="currentExecution?.workflow_name || ''":execution-id="executionId":status="currentExecution?.status":progress="progress":duration="duration":trigger-log-id="currentExecution?.trigger_log_id":retry-from-id="retryFromId":resumed-from-id="resumedFromId":is-pausing="isPausing":is-resuming="isResuming":is-cancelling="isCancelling":is-retrying="isRetrying"
 @pause="handlePause"
 @resume="handleResume"
 @cancel="handleCancel"
 @retry="handleRetry"
 @refresh="store.fetchExecution(executionId)"
 @back="router.push('/executions')"
 />
 <ExecutionStatusBanners:ws-disconnected="wsDisconnected":is-debug-execution="isDebugExecution":is-active-status="isActiveStatus(currentExecution?.status)":is-breakpoint-mode="isBreakpointMode":debug-paused-node-name="debugPausedNodeName"
 @reconnect-ws="store.connectWebSocket(executionId)"
 @cancel-debug="handleCancelDebug"
 @update:is-breakpoint-mode="isBreakpointMode = $event"
 />
 <ExecutionContent:loading="loading":error="error":current-execution="currentExecution":cost-data="costData":cost-loading="costLoading":timeline-data="timelineData":definition-changed="definitionChanged":breakpoints="breakpoints":is-debug-execution="isDebugExecution":is-pre-execution-failure="isPreExecutionFailure":is-terminal-status="isTerminalStatus(currentExecution?.status)"
 @node-click="handleNodeClick"
 @resume-click="handleResumeClick"
 @debug-release="handleDebugRelease"
 @debug-skip="handleDebugSkip"
 @toggle-breakpoint="handleToggleBreakpoint"
 @retry="handleRetry"
 />
 <!-- 节点详情抽屉 -->
 <NodeDetailSheet:open="sheetOpen":node-execution="selectedNodeExecution":node-config="selectedNodeConfig":bottleneck-info="selectedBottleneckInfo":execution-id="executionId":can-resume="!definitionChanged && (selectedNodeExecution?.status === 'failed')":is-debug-paused="isSelectedNodeDebugPaused":workflow-definition="currentExecution?.workflow_definition"
 @update:open="sheetOpen = $event"
 @action-complete="handleActionComplete"
 @resume-from-node="handleResumeClick"
 />
 <ExecutionDialogs:approval-dialog-open="approvalDialogOpen":approval-comment="approvalComment":approving="approving":selected-node-execution="selectedNodeExecution":trigger-dialog-open="triggerDialogOpen":trigger-input-data="triggerInputData":triggering="triggering":resume-dialog-open="resumeDialogOpen":resume-node-name="resumeNodeName":resume-preview-loading="resumePreviewLoading":resume-skip-nodes="resumeSkipNodes":resume-rerun-nodes="resumeRerunNodes":resuming="resuming"
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
