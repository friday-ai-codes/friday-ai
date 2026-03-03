<script setup lang="ts">
/**
 * 执行详情页 — 全屏 DAG 视图
 *
 * 布局：紧凑顶部栏 + 全屏 ExecutionDagView + 右侧 NodeDetailSheet。
 * 节点状态通过 WebSocket 实时更新，执行完成后自动加载 Timeline 瓶颈数据。
 */
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import ExecutionDagView from '~/components/execution/dag/ExecutionDagView.vue'
import NodeDetailSheet from '~/components/execution/NodeDetailSheet.vue'
import ExecutionStatusBadge from '~/components/execution/ExecutionStatusBadge.vue'
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
import { Textarea } from '~/components/ui/textarea'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
const route = useRoute
const router = useRouter
const executionId = computed( => (route.params as { id: string }).id)
const store = useExecutionsStore
const { currentExecution, timelineData, loading, error, wsStatus } = storeToRefs(store)
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
 if (!currentExecution.value) return false
 if (!isActiveStatus(currentExecution.value.status)) return false
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
 // 执行结束时获取 Timeline 瓶颈数据
 if (isTerminalStatus(newStatus) && !isTerminalStatus(oldStatus)) {
 store.fetchTimeline(executionId.value)
 }
})
// ----- 计算属性 -----
const progress = computed( => currentExecution.value?.progress || 0)
const duration = computed( => {
 if (!currentExecution.value?.duration) return '-'
 const seconds = Math.round(currentExecution.value.duration)
 if (seconds < 60) return `${seconds}s`
 const minutes = Math.floor(seconds / 60)
 const remainingSeconds = seconds % 60
 return `${minutes}m ${remainingSeconds}s`
})
/** 选中节点的配置（从 workflow_definition 中查找） */
const selectedNodeConfig = computed<Record<string, unknown>>( => {
 if (!selectedNodeId.value || !currentExecution.value?.workflow_definition) return {}
 const defNode = currentExecution.value.workflow_definition.nodes.find(
 n => n.id === selectedNodeId.value,
 )
 return defNode?.config ?? {}
})
/** 选中节点的瓶颈信息 */
const selectedBottleneckInfo = computed( => {
 if (!selectedNodeExecution.value || !timelineData.value) return null
 const tlNode = timelineData.value.nodes.find(
 n => n.node_id === selectedNodeExecution.value!.node,
 )
 if (!tlNode?.is_bottleneck) return null
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
 await store.resumeExecution(executionId.value)
 toast.success('工作流已恢复')
}
async function handleCancel {
 await store.cancelExecution(executionId.value)
 toast.success('工作流已取消')
}
async function handleRetry {
 if (!currentExecution.value) return
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
// ----- 审批/触发对话框（备用入口） -----
async function handleApprove {
 if (!selectedNodeExecution.value) return
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
 if (!selectedNodeExecution.value) return
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
 if (!selectedNodeExecution.value) return
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
 <div class="text-[10px] text-muted-foreground font-mono truncate">
 {{ executionId }}
 </div>
 </div>
 </div>
 <!-- 中部：状态 + 进度 + 耗时 -->
 <div v-if="currentExecution" class="flex items-center gap-3">
 <ExecutionStatusBadge:status="currentExecution.status" size="sm" />
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
 v-if="!currentExecution.workflow_definition"
 class="h-full flex items-center justify-center text-muted-foreground"
 >
 <div class="text-center space-y-2">
 <span class="icon-[lucide--layout-grid] w-12 mx-auto opacity-30" />
 <p class="text-sm">此执行没有保存工作流定义快照，无法渲染 DAG 视图</p>
 <p class="text-xs text-muted-foreground/60">该执行可能在快照功能上线前创建</p>
 </div>
 </div>
 <!-- DAG 视图 -->
 <ExecutionDagView
 v-else:execution="currentExecution":timeline-data="timelineData"
 @node-click="handleNodeClick"
 />
 <!-- 错误信息浮层（如果有全局错误消息） -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="translate-y-2 opacity-0"
 enter-to-class="translate-y-0 opacity-100"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="translate-y-0 opacity-100"
 leave-to-class="translate-y-2 opacity-0"
 >
 <div
 v-if="currentExecution.error_message"
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
 <NodeDetailSheet:open="sheetOpen":node-execution="selectedNodeExecution":node-config="selectedNodeConfig":bottleneck-info="selectedBottleneckInfo":execution-id="executionId"
 @update:open="sheetOpen = $event"
 @action-complete="handleActionComplete"
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
 </div>
</template>
