<script setup lang="ts">
import type { ResumePreviewNode } from '~/api/workflow'
/**
 * 执行详情页 — 全屏 DAG 视图
 *
 * 布局：紧凑顶部栏 + 全屏 ExecutionDagView + 右侧 NodeDetailSheet。
 * 节点状态通过 WebSocket 实时更新，执行完成后自动加载 Timeline 瓶颈数据。
 */
import type { NodeExecution } from '~/stores/useExecutionsStore'
import type { CostBreakdown } from '~/types/execution'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { checkWorkflowChanged, getCostBreakdown, resumeFromFailed, resumePreview } from '~/api/workflow'
import CostSummaryBar from '~/components/execution/CostSummaryBar.vue'
import ExecutionDagView from '~/components/execution/dag/ExecutionDagView.vue'
import ExecutionStatusBadge from '~/components/execution/ExecutionStatusBadge.vue'
import NodeDetailSheet from '~/components/execution/NodeDetailSheet.vue'
import ProviderCostTable from '~/components/execution/ProviderCostTable.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent } from '~/components/ui/card'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Progress } from '~/components/ui/progress'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
const route = useRoute
const router = useRouter
const executionId = computed( => (route.params as { id: string }).id)
const store = useExecutionsStore
const { currentExecution, timelineData, loading, error, wsStatus } = storeToRefs(store)
/** Phase: 是否为调试执行 */
const isDebugExecution = computed( => currentExecution.value?.is_debug === true)
/** Phase: 当前调试暂停节点名称 */
const debugPausedNodeName = computed( => {
 const nodeId = currentExecution.value?.debug_paused_at_node
 if (!nodeId || !currentExecution.value?.workflow_definition)
 return null
 const defNode = currentExecution.value.workflow_definition.nodes.find(n => n.id === nodeId)
 return defNode?.name ?? nodeId
})
// ----- 抽屉状态 -----
const sheetOpen = ref(false)
const selectedNodeExecution = ref<NodeExecution | null>(null)
const selectedNodeId = ref<string | null>(null)
// ----- 对话框状态（保留 Approval + Trigger 作为备用） -----
const approvalDialogOpen = ref(false)
const approvalComment = ref('')
const approving = ref(false)
const triggerDialogOpen = ref(false)
const triggerInputData = ref('')
const triggering = ref(false)
// ----- 成本数据 -----
const costData = ref<CostBreakdown | null>(null)
const costLoading = ref(false)
async function fetchCostData {
 costLoading.value = true
 try {
 costData.value = await getCostBreakdown(executionId.value)
 }
 catch {
 // 成本数据是辅助信息，加载失败不阻塞
 costData.value = null
 }
 finally {
 costLoading.value = false
 }
}
// ----- 变更检测（Phase） -----
const definitionChanged = ref(false)
async function fetchDefinitionChanged {
 // 只对已结束的执行检测
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
// ----- 从此继续对话框（Phase → Phase 增强） -----
const resumeDialogOpen = ref(false)
const resumeNodeId = ref<string | null>(null)
const resumeNodeName = ref('')
const resumeSkipCount = ref(0)
const resuming = ref(false)
const resumeSkipNodes = ref<ResumePreviewNode>
const resumeRerunNodes = ref<ResumePreviewNode>
const resumePreviewLoading = ref(false)
// ----- 活跃状态判断 -----
function isActiveStatus(status?: string) {
 return ['running', 'pending', 'queued', 'paused', 'waiting_approval', 'waiting_event', 'suspended'].includes(status || '')
}
/** 执行是否已结束（用于触发 Timeline 加载） */
function isTerminalStatus(status?: string) {
 return ['completed', 'failed', 'cancelled', 'timeout'].includes(status || '')
}
/** WebSocket 断线检测 */
const wsDisconnected = computed( => {
 if (!currentExecution.value)
 return false
 if (!isActiveStatus(currentExecution.value.status))
 return false
 return wsStatus.value === 'CLOSED'
})
// ----- 生命周期 -----
onMounted(async => {
 await store.fetchExecution(executionId.value)
 if (isActiveStatus(currentExecution.value?.status)) {
 store.connectWebSocket(executionId.value)
 }
 // 如果已结束，立即加载 timeline 瓶颈数据
 if (isTerminalStatus(currentExecution.value?.status)) {
 store.fetchTimeline(executionId.value)
 }
 // 并行加载成本数据 + 变更检测
 fetchCostData
 fetchDefinitionChanged
})
onUnmounted( => {
 store.disconnectWebSocket
})
// 监听状态变化：连接/断开 WS + 加载 Timeline
watch( => currentExecution.value?.status, (newStatus, oldStatus) => {
 if (isActiveStatus(newStatus) && !isActiveStatus(oldStatus)) {
 store.connectWebSocket(executionId.value)
 }
 else if (!isActiveStatus(newStatus) && isActiveStatus(oldStatus)) {
 store.disconnectWebSocket
 }
 // 执行结束时获取 Timeline 瓶颈数据 + 成本数据
 if (isTerminalStatus(newStatus) && !isTerminalStatus(oldStatus)) {
 store.fetchTimeline(executionId.value)
 if (!costData.value)
 fetchCostData
 }
})
// ----- 计算属性 -----
/** 预执行失败：执行在节点运行前就失败（如 DAG 验证错误） */
const isPreExecutionFailure = computed( => {
 const exec = currentExecution.value
 if (!exec)
 return false
 return exec.status === 'failed'
 && exec.total_nodes === 0
 && exec.completed_nodes === 0
 && exec.failed_nodes === 0
 && !!exec.error_message
})
const progress = computed( => currentExecution.value?.progress || 0)
const duration = computed( => {
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
const retryFromId = computed( => {
 const metadata = currentExecution.value?.trigger_data?.metadata
 return metadata?.retry_from || null
})
/** 检测是否为「从此继续」执行，提取原始执行 ID */
const resumedFromId = computed( => {
 return currentExecution.value?.resumed_from || null
})
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
 // 计算排名：critical 排在最前面
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
// ----- Phase: 断点状态管理 -----
/** 断点集合 */
const breakpoints = ref<Set<string>>(new Set)
/** 当前调试模式 */
const debugMode = ref<'step' | 'breakpoint'>('step')
/** 是否为断点模式（双向绑定用于 Switch） */
const isBreakpointMode = computed({
 get: => debugMode.value === 'breakpoint',
 set: (val: boolean) => {
 debugMode.value = val ? 'breakpoint': 'step'
 store.sendDebugModeSwitch(debugMode.value)
 },
})
/** 切换节点断点 */
function handleToggleBreakpoint(nodeId: string) {
 if (breakpoints.value.has(nodeId)) {
 breakpoints.value.delete(nodeId)
 store.sendBreakpointAction('remove_breakpoint', nodeId)
 }
 else {
 breakpoints.value.add(nodeId)
 store.sendBreakpointAction('set_breakpoint', nodeId)
 }
 // 触发响应式更新
 breakpoints.value = new Set(breakpoints.value)
}
/** 执行切换时重置断点状态 */
watch( => currentExecution.value?.id, => {
 breakpoints.value = new Set
 debugMode.value = 'step'
})
// ----- Phase: 调试操作 -----
/** 调试放行 */
function handleDebugRelease(_nodeId: string) {
 store.sendDebugAction('release')
}
/** 调试跳过 */
function handleDebugSkip(_nodeId: string) {
 store.sendDebugAction('skip')
}
/** 终止调试（取消执行） */
async function handleCancelDebug {
 await store.cancelExecution(executionId.value)
 toast.success('调试执行已终止')
}
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
// ----- 顶部栏操作按钮 -----
async function handlePause {
 await store.pauseExecution(executionId.value)
 toast.success('工作流已暂停')
}
async function handleResume {
 try {
 await store.resumeExecution(executionId.value)
 toast.success('工作流已恢复')
 }
 catch (e: any) {
 toast.error(`恢复失败: ${e.message}`)
 }
}
async function handleCancel {
 await store.cancelExecution(executionId.value)
 toast.success('工作流已取消')
}
async function handleRetry {
 if (!currentExecution.value)
 return
 try {
 const { retryExecution } = await import('~/api/workflow')
 const result = await retryExecution(currentExecution.value.id)
 if (result?.execution_id) {
 toast.success('工作流重新执行成功')
 router.push(`/executions/${result.execution_id}`)
 }
 }
 catch (e: any) {
 toast.error(`重试失败: ${e.message}`)
 }
}
// ----- 从此继续（Phase → Phase 增强） -----
async function handleResumeClick(nodeId: string) {
 const exec = currentExecution.value
 if (!exec?.workflow_definition)
 return
 // 找到节点名称
 const defNode = exec.workflow_definition.nodes.find(n => n.id === nodeId)
 resumeNodeName.value = defNode?.name ?? nodeId
 resumeNodeId.value = nodeId
 resumeDialogOpen.value = true
 // 异步加载影响范围
 resumePreviewLoading.value = true
 resumeSkipNodes.value =
 resumeRerunNodes.value =
 try {
 const preview = await resumePreview(executionId.value, nodeId)
 resumeSkipNodes.value = preview.skip_nodes
 resumeRerunNodes.value = preview.rerun_nodes
 resumeSkipCount.value = preview.total_skip
 }
 catch {
 // 预览加载失败不阻止恢复操作，使用 fallback
 resumeSkipCount.value = (exec.completed_nodes ?? 0) + (exec.skipped_nodes ?? 0)
 }
 finally {
 resumePreviewLoading.value = false
 }
}
async function handleResumeFromFailed {
 if (!resumeNodeId.value)
 return
 resuming.value = true
 try {
 const result = await resumeFromFailed(executionId.value, resumeNodeId.value)
 if (result?.execution_id) {
 toast.success('已从失败节点继续执行')
 resumeDialogOpen.value = false
 router.push(`/executions/${result.execution_id}`)
 }
 }
 catch (e: any) {
 if (e.status === 409) {
 toast.error('工作流定义已修改，无法从此继续')
 definitionChanged.value = true
 resumeDialogOpen.value = false
 }
 else {
 toast.error(`继续执行失败: ${e.message}`)
 }
 }
 finally {
 resuming.value = false
 }
}
// ----- 审批/触发对话框（备用入口） -----
async function handleApprove {
 if (!selectedNodeExecution.value)
 return
 approving.value = true
 try {
 await store.approveNode(selectedNodeExecution.value.id, approvalComment.value)
 approvalDialogOpen.value = false
 approvalComment.value = ''
 toast.success('节点已批准')
 }
 catch (e: any) {
 toast.error(`批准失败: ${e.message}`)
 }
 finally {
 approving.value = false
 }
}
async function handleReject {
 if (!selectedNodeExecution.value)
 return
 approving.value = true
 try {
 await store.rejectNode(selectedNodeExecution.value.id, approvalComment.value)
 approvalDialogOpen.value = false
 approvalComment.value = ''
 toast.success('节点已拒绝')
 }
 catch (e: any) {
 toast.error(`拒绝失败: ${e.message}`)
 }
 finally {
 approving.value = false
 }
}
async function handleTrigger {
 if (!selectedNodeExecution.value)
 return
 triggering.value = true
 try {
 let inputData = {}
 if (triggerInputData.value.trim) {
 try {
 inputData = JSON.parse(triggerInputData.value)
 }
 catch {
 toast.error('输入数据格式错误，请输入有效的 JSON')
 triggering.value = false
 return
 }
 }
 await store.triggerNode(selectedNodeExecution.value.id, inputData)
 triggerDialogOpen.value = false
 triggerInputData.value = '{}'
 toast.success('节点已触发')
 }
 catch (e: any) {
 toast.error(`触发失败: ${e.message}`)
 }
 finally {
 triggering.value = false
 }
}
</script>
<template>
 <div class="h-screen flex flex-col overflow-hidden">
 <!-- ===== 紧凑顶部栏 ===== -->
 <header
 class="shrink-0 flex items-center justify-between px-4 py-2
 bg-background/80 backdrop-blur-sm border-b border-border/50 z-20"
 >
 <!-- 左侧：返回 + 名称 -->
 <div class="flex items-center gap-3 min-w-0">
 <Button variant="ghost" size="icon" class="shrink-0 w-8" @click="router.push('/executions')">
 <span class="icon-[lucide--arrow-left] w-4 " />
 </Button>
 <div class="min-w-0">
 <div class="text-sm font-semibold truncate">
 {{ currentExecution?.workflow_name || '工作流执行' }}
 </div>
 <div class="flex items-center gap-2">
 <span class="text-[10px] text-muted-foreground font-mono truncate">
 {{ executionId }}
 </span>
 <RouterLink
 v-if="currentExecution?.trigger_log_id":to="`/logs/triggers/${currentExecution.trigger_log_id}`"
 class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors shrink-0"
 @click.stop
 >
 <span class="icon-[lucide--file-text] w-3 " />
 来源日志
 </RouterLink>
 </div>
 </div>
 </div>
 <!-- 中部：状态 + 进度 + 耗时 -->
 <div v-if="currentExecution" class="flex items-center gap-3">
 <ExecutionStatusBadge:status="currentExecution.status" size="sm" />
 <!-- 重试来源标记 -->
 <div v-if="retryFromId" class="flex items-center gap-1.5">
 <Badge variant="warning" class="text-[10px] px-1.5 py-0">
 重试
 </Badge>
 <RouterLink:to="`/executions/${retryFromId}`"
 class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors"
 >
 原始执行
 <span class="icon-[lucide--external-link] w-2.5 .5" />
 </RouterLink>
 </div>
 <!-- 从此继续来源标记（Phase） -->
 <div v-if="resumedFromId" class="flex items-center gap-1.5">
 <Badge variant="outline" class="border-primary/50 text-primary text-[10px] px-1.5 py-0">
 继续
 </Badge>
 <RouterLink:to="`/executions/${resumedFromId}`"
 class="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-primary transition-colors"
 >
 原始执行
 <span class="icon-[lucide--external-link] w-2.5 .5" />
 </RouterLink>
 </div>
 <div class="hidden sm:flex items-center gap-2 text-xs text-muted-foreground">
 <Progress:model-value="progress" class="w-24 .5" />
 <span class="tabular-nums whitespace-nowrap">{{ Math.round(progress) }}%</span>
 </div>
 <div class="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
 {{ duration }}
 </div>
 </div>
 <!-- 右侧：操作按钮 -->
 <div class="flex items-center gap-1.5">
 <Button
 v-if="currentExecution?.status === 'running'"
 variant="outline"
 size="sm"
 class=" text-xs"
 @click="handlePause"
 >
 <span class="icon-[lucide--pause] w-3.5 .5 mr-1" />
 暂停
 </Button>
 <Button
 v-if="currentExecution?.status === 'paused'"
 variant="outline"
 size="sm"
 class=" text-xs"
 @click="handleResume"
 >
 <span class="icon-[lucide--play] w-3.5 .5 mr-1" />
 继续
 </Button>
 <Button
 v-if="['running', 'paused', 'pending', 'waiting_approval', 'waiting_event', 'suspended'].includes(currentExecution?.status || '')"
 variant="destructive"
 size="sm"
 class=" text-xs"
 @click="handleCancel"
 >
 <span class="icon-[lucide--square] w-3.5 .5 mr-1" />
 取消
 </Button>
 <Button
 v-if="currentExecution?.status === 'failed' || currentExecution?.status === 'cancelled'"
 variant="default"
 size="sm"
 class=" text-xs"
 @click="handleRetry"
 >
 <span class="icon-[lucide--rotate-ccw] w-3.5 .5 mr-1" />
 重试
 </Button>
 <Button variant="ghost" size="icon" class=" w-7" @click="store.fetchExecution(executionId)">
 <span class="icon-[lucide--refresh-cw] w-3.5 .5" />
 </Button>
 </div>
 </header>
 <!-- ===== WebSocket 断线警告条 ===== -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="-translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="-translate-y-2 opacity-0"
 >
 <div
 v-if="wsDisconnected"
 class="shrink-0 flex items-center justify-center gap-2 bg-amber-500/90 backdrop-blur-sm text-white text-sm px-4 py-1.5 z-10"
 >
 <span class="icon-[lucide--wifi-off] w-4 " />
 <span>连接已断开，状态可能不是最新</span>
 <button
 class="ml-2 text-xs underline underline-offset-2 hover:no-underline"
 @click="store.connectWebSocket(executionId)"
 >
 重新连接
 </button>
 </div>
 </Transition>
 <!-- ===== Phase: 调试模式横幅 ===== -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="-translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="-translate-y-2 opacity-0"
 >
 <div
 v-if="isDebugExecution && isActiveStatus(currentExecution?.status)"
 class="shrink-0 flex items-center justify-between bg-amber-500/90 backdrop-blur-sm text-white px-4 py-2 z-10"
 >
 <div class="flex items-center gap-2 text-sm">
 <span class="icon-[lucide--bug] w-4 " />
 <span class="font-medium">调试模式</span>
 <!-- Phase: 逐步/断点模式切换 -->
 <div class="flex items-center gap-1.5 ml-3 pl-3 border-l border-white/30">
 <span class="text-xs text-white/70">逐步</span>
 <Switch:checked="isBreakpointMode"
 class="data-[state=checked]:bg-white/30 data-[state=unchecked]:bg-white/20 w-7"
 @update:checked="isBreakpointMode = $event"
 />
 <span class="text-xs text-white/70">断点</span>
 </div>
 <span v-if="debugPausedNodeName" class="text-white/80">
 · 暂停在「{{ debugPausedNodeName }}」
 </span>
 </div>
 <Button
 variant="ghost"
 size="sm"
 class="text-white hover:bg-white/20 text-xs"
 @click="handleCancelDebug"
 >
 <span class="icon-[lucide--square] w-3.5 .5 mr-1" />
 终止调试
 </Button>
 </div>
 </Transition>
 <!-- ===== 主内容区域 ===== -->
 <!-- 加载状态 -->
 <div v-if="loading && !currentExecution" class="flex-1 flex items-center justify-center">
 <span class="icon-[lucide--loader-2] w-8 animate-spin text-primary" />
 </div>
 <!-- 错误状态 -->
 <div v-else-if="error" class="flex-1 flex items-center justify-center ">
 <Card class="border-destructive max-w-md w-full">
 <CardContent class="py-6 text-center text-destructive">
 <span class="icon-[lucide--x-circle] w-12 mx-auto mb-4" />
 <p>{{ error }}</p>
 </CardContent>
 </Card>
 </div>
 <!-- DAG 画布（全屏占满顶部栏以下空间） -->
 <div v-else-if="currentExecution" class="flex-1 min- relative">
 <!-- 无 workflow_definition 时的回退提示 -->
 <div
 v-if="!currentExecution.workflow_definition?.nodes?.length"
 class="h-full flex items-center justify-center text-muted-foreground"
 >
 <div class="text-center space-y-2">
 <span class="icon-[lucide--layout-grid] w-12 mx-auto opacity-30" />
 <p class="text-sm">
 此执行没有保存工作流定义快照，无法渲染 DAG 视图
 </p>
 <p class="text-xs text-muted-foreground/60">
 该执行可能在快照功能上线前创建
 </p>
 </div>
 </div>
 <!-- DAG 视图 -->
 <ExecutionDagView
 v-else:execution="currentExecution":timeline-data="timelineData":cost-data="costData":definition-changed="definitionChanged":breakpoints="breakpoints":is-debug-execution="isDebugExecution"
 @node-click="handleNodeClick"
 @resume-click="handleResumeClick"
 @debug-release="handleDebugRelease"
 @debug-skip="handleDebugSkip"
 @toggle-breakpoint="handleToggleBreakpoint"
 />
 <!-- 成本摘要浮层（右上角） -->
 <div class="absolute top-3 right-3 z-10 space-y-2">
 <CostSummaryBar:cost-summary="costData?.summary ?? null":loading="costLoading"
 />
 <ProviderCostTable
 v-if="costData && isTerminalStatus(currentExecution?.status)":cost-data="costData"
 />
 </div>
 <!-- 预执行失败：居中醒目展示（DAG 验证等初始化阶段错误） -->
 <div
 v-if="isPreExecutionFailure"
 class="absolute inset-0 z-20 flex items-center justify-center bg-background/60 backdrop-blur-sm"
 >
 <div class="max-w-md w-full mx-4">
 <div class="bg-red-50 dark:bg-red-900/20 border border-red-200/60 dark:border-red-800/50 rounded-2xl shadow-xl space-y-3">
 <div class="flex items-center gap-3">
 <div class="shrink-0 w-10 rounded-full bg-red-100 dark:bg-red-900/40 flex items-center justify-center">
 <span class="icon-[lucide--alert-triangle] w-5 text-red-500" />
 </div>
 <div>
 <h3 class="text-sm font-semibold text-red-700 dark:text-red-300">
 工作流启动失败
 </h3>
 <p class="text-xs text-red-500/70 dark:text-red-400/70">
 执行在节点运行前终止
 </p>
 </div>
 </div>
 <pre class="text-sm text-red-700 dark:text-red-300 whitespace-pre-wrap break-words bg-red-100/50 dark:bg-red-900/30 rounded-xl px-4 py-3">{{ currentExecution.error_message }}</pre>
 <div class="flex justify-end">
 <Button
 variant="outline"
 size="sm"
 class="border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
 @click="handleRetry"
 >
 <span class="icon-[lucide--rotate-ccw] w-3.5 .5 mr-1.5" />
 重新执行
 </Button>
 </div>
 </div>
 </div>
 </div>
 <!-- 运行时错误信息浮层（节点执行后的全局错误） -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="translate-y-2 opacity-0"
 >
 <div
 v-if="currentExecution.error_message && !isPreExecutionFailure"
 class="absolute bottom-4 left-4 right-4 max-w-lg mx-auto z-10"
 >
 <div class="bg-red-50 dark:bg-red-900/30 backdrop-blur-sm border border-red-200/50 dark:border-red-800/50 rounded-2xl px-4 py-3 shadow-lg">
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--alert-circle] w-4 text-red-500 mt-0.5 shrink-0" />
 <p class="text-sm text-red-700 dark:text-red-300 line-clamp-3">
 {{ currentExecution.error_message }}
 </p>
 </div>
 </div>
 </div>
 </Transition>
 </div>
 <!-- ===== 节点详情抽屉 ===== -->
 <NodeDetailSheet:open="sheetOpen":node-execution="selectedNodeExecution":node-config="selectedNodeConfig":bottleneck-info="selectedBottleneckInfo":execution-id="executionId":can-resume="!definitionChanged && (selectedNodeExecution?.status === 'failed')":is-debug-paused="isSelectedNodeDebugPaused":workflow-definition="currentExecution?.workflow_definition"
 @update:open="sheetOpen = $event"
 @action-complete="handleActionComplete"
 @resume-from-node="handleResumeClick"
 />
 <!-- ===== 备用对话框（审批） ===== -->
 <Dialog v-model:open="approvalDialogOpen">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>审核: {{ selectedNodeExecution?.node_name }}</DialogTitle>
 <DialogDescription>
 请审核此节点的执行结果并选择批准或拒绝。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4">
 <div v-if="selectedNodeExecution?.approval_data?.display_data" class=" rounded-lg bg-muted">
 <pre class="text-xs">{{ JSON.stringify(selectedNodeExecution.approval_data.display_data, null, 2) }}</pre>
 </div>
 <div class="space-y-2">
 <label class="text-sm font-medium">备注（可选）</label>
 <Textarea v-model="approvalComment" placeholder="添加备注..." />
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="approvalDialogOpen = false">
 取消
 </Button>
 <Button variant="destructive":disabled="approving" @click="handleReject">
 <span class="icon-[lucide--x-circle] w-4 mr-2" />
 拒绝
 </Button>
 <Button:disabled="approving" @click="handleApprove">
 <span class="icon-[lucide--check-circle] w-4 mr-2" />
 批准
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 <!-- ===== 备用对话框（手动触发） ===== -->
 <Dialog v-model:open="triggerDialogOpen">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>触发: {{ selectedNodeExecution?.node_name }}</DialogTitle>
 <DialogDescription>
 输入触发数据以启动工作流执行。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4">
 <div class="space-y-2">
 <label class="text-sm font-medium">输入数据（JSON 格式）</label>
 <Textarea
 v-model="triggerInputData"
 placeholder="{&quot;key&quot;: &quot;value&quot;}"
 class="font-mono min-"
 />
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="triggerDialogOpen = false">
 取消
 </Button>
 <Button:disabled="triggering" @click="handleTrigger">
 <span class="icon-[lucide--zap] w-4 mr-2" />
 触发
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 <!-- ===== 从此继续确认对话框（Phase → Phase 增强） ===== -->
 <Dialog v-model:open="resumeDialogOpen">
 <DialogContent class="max-w-md">
 <DialogHeader>
 <DialogTitle>从此继续执行</DialogTitle>
 <DialogDescription>
 将从「{{ resumeNodeName }}」节点开始重新执行。
 </DialogDescription>
 </DialogHeader>
 <!-- 影响范围详情 -->
 <div v-if="resumePreviewLoading" class="flex items-center justify-center py-4">
 <span class="icon-[lucide--loader-2] w-5 animate-spin text-muted-foreground" />
 <span class="ml-2 text-sm text-muted-foreground">正在分析影响范围...</span>
 </div>
 <div v-else class="space-y-3">
 <!-- 将被跳过的节点 -->
 <div v-if="resumeSkipNodes.length > 0">
 <p class="text-xs font-medium text-muted-foreground mb-1.5">
 <span class="icon-[lucide--skip-forward] w-3.5 .5 inline-block mr-1 align-text-bottom" />
 跳过（复用结果） · {{ resumeSkipNodes.length }} 个
 </p>
 <div class="flex flex-wrap gap-1">
 <Badge v-for="node in resumeSkipNodes":key="node.id" variant="secondary" class="text-xs">
 {{ node.name }}
 </Badge>
 </div>
 </div>
 <!-- 将重新执行的节点 -->
 <div v-if="resumeRerunNodes.length > 0">
 <p class="text-xs font-medium text-muted-foreground mb-1.5">
 <span class="icon-[lucide--play] w-3.5 .5 inline-block mr-1 align-text-bottom" />
 重新执行 · {{ resumeRerunNodes.length }} 个
 </p>
 <div class="flex flex-wrap gap-1">
 <Badge v-for="node in resumeRerunNodes":key="node.id" variant="outline" class="text-xs border-primary/50">
 {{ node.name }}
 </Badge>
 </div>
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="resumeDialogOpen = false">
 取消
 </Button>
 <Button:disabled="resuming || resumePreviewLoading" @click="handleResumeFromFailed">
 <span v-if="resuming" class="icon-[lucide--loader-2] w-4 mr-2 animate-spin" />
 <span v-else class="icon-[lucide--play-circle] w-4 mr-2" />
 确认继续
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 </div>
</template>
