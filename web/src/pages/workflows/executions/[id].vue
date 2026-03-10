<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { AlertCircle, ArrowLeft, CheckCircle, ChevronRight, Clock, Loader2, Pause, Play, RefreshCw, RotateCcw, Square, XCircle, Zap } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import NodeDebugPanel from '~/components/execution/NodeDebugPanel.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Progress } from '~/components/ui/progress'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import { Textarea } from '~/components/ui/textarea'
import { cn } from '~/lib/utils'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
const route = useRoute('/workflows/executions/[id]')
const router = useRouter
const executionId = route.params.id
const store = useExecutionsStore
const { currentExecution, loading, error } = storeToRefs(store)
// Selected node for detail view
const selectedNodeExecution = ref<NodeExecution | null>(null)
// Approval dialog state
const approvalDialogOpen = ref(false)
const approvalComment = ref('')
const approving = ref(false)
// Manual trigger dialog state
const triggerDialogOpen = ref(false)
const triggerInputData = ref('')
const triggering = ref(false)
// Polling state
let pollTimer: ReturnType<typeof setInterval> | null = null
onMounted(async => {
 await store.fetchExecution(executionId)
 startPolling
})
onUnmounted( => {
 stopPolling
})
function startPolling {
 if (pollTimer)
 return
 // Initial check
 if (isActiveStatus(currentExecution.value?.status)) {
 pollTimer = setInterval(async => {
 // Only fetch if we are still on the same page and execution is active
 if (route.params.id === executionId) {
 await store.fetchExecution(executionId)
 if (!isActiveStatus(currentExecution.value?.status)) {
 stopPolling
 }
 }
 else {
 stopPolling
 }
 }, 5000)
 }
}
function stopPolling {
 if (pollTimer) {
 clearInterval(pollTimer)
 pollTimer = null
 }
}
function isActiveStatus(status?: string) {
 return ['running', 'pending', 'queued', 'paused', 'waiting_approval'].includes(status || '')
}
// Watch for status changes to start/stop polling (e.g. if resumed)
watch( => currentExecution.value?.status, (newStatus) => {
 if (isActiveStatus(newStatus)) {
 startPolling
 }
 else {
 stopPolling
 }
})
// Status helpers
const statusConfig = {
 pending: { icon: Clock, color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800', label: '等待中', animate: false },
 running: { icon: Loader2, color: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900/30', label: '运行中', animate: true },
 completed: { icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-100 dark:bg-green-900/30', label: '已完成', animate: false },
 failed: { icon: XCircle, color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30', label: '失败', animate: false },
 paused: { icon: Pause, color: 'text-yellow-500', bg: 'bg-yellow-100 dark:bg-yellow-900/30', label: '已暂停', animate: false },
 cancelled: { icon: Square, color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800', label: '已取消', animate: false },
 waiting_approval: { icon: AlertCircle, color: 'text-orange-500', bg: 'bg-orange-100 dark:bg-orange-900/30', label: '待审批', animate: false },
 skipped: { icon: ChevronRight, color: 'text-gray-400', bg: 'bg-gray-100 dark:bg-gray-800', label: '已跳过', animate: false },
 timeout: { icon: Clock, color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30', label: '超时', animate: false },
}
const getStatusConfig = (status: string) => statusConfig[status as keyof typeof statusConfig] || statusConfig.pending
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
// Actions
async function handlePause {
 await store.pauseExecution(executionId)
 toast.success('工作流已暂停')
}
async function handleResume {
 try {
 await store.resumeExecution(executionId)
 toast.success('工作流已恢复')
 }
 catch (e: any) {
 toast.error(`恢复失败: ${e.message}`)
 }
}
async function handleCancel {
 await store.cancelExecution(executionId)
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
 router.push(`/workflows/executions/${result.execution_id}`)
 }
 }
 catch (e: any) {
 toast.error(`重试失败: ${e.message}`)
 }
}
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
function openApprovalDialog(nodeExec: NodeExecution) {
 selectedNodeExecution.value = nodeExec
 approvalDialogOpen.value = true
}
function openTriggerDialog(nodeExec: NodeExecution) {
 selectedNodeExecution.value = nodeExec
 triggerInputData.value = '{}'
 triggerDialogOpen.value = true
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
function formatTime(dateStr: string | null) {
 if (!dateStr)
 return '-'
 return new Date(dateStr).toLocaleTimeString
}
</script>
<template>
 <div class="container py-6 space-y-6">
 <!-- Header -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-4">
 <Button variant="ghost" size="icon" @click="router.back">
 <ArrowLeft class="w-5 " />
 </Button>
 <div>
 <h1 class="text-2xl font-bold">
 {{ currentExecution?.workflow_name || '工作流执行' }}
 </h1>
 <p class="text-sm text-muted-foreground font-mono">
 {{ executionId }}
 </p>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <Button
 v-if="currentExecution?.status === 'running'"
 variant="outline"
 size="sm"
 @click="handlePause"
 >
 <Pause class="w-4 mr-2" />
 暂停
 </Button>
 <Button
 v-if="currentExecution?.status === 'paused'"
 variant="outline"
 size="sm"
 @click="handleResume"
 >
 <Play class="w-4 mr-2" />
 继续
 </Button>
 <Button
 v-if="['running', 'paused', 'pending', 'waiting_approval'].includes(currentExecution?.status || '')"
 variant="destructive"
 size="sm"
 @click="handleCancel"
 >
 <Square class="w-4 mr-2" />
 取消
 </Button>
 <Button
 v-if="currentExecution?.status === 'failed' || currentExecution?.status === 'cancelled'"
 variant="default"
 size="sm"
 @click="handleRetry"
 >
 <RotateCcw class="w-4 mr-2" />
 重试
 </Button>
 <Button variant="ghost" size="icon" @click="store.fetchExecution(executionId)">
 <RefreshCw class="w-4 " />
 </Button>
 </div>
 </div>
 <!-- Loading state -->
 <div v-if="loading && !currentExecution" class="flex justify-center py-12">
 <Loader2 class="w-8 animate-spin text-primary" />
 </div>
 <!-- Error state -->
 <Card v-else-if="error" class="border-destructive">
 <CardContent class="py-6 text-center text-destructive">
 <XCircle class="w-12 mx-auto mb-4" />
 <p>{{ error }}</p>
 </CardContent>
 </Card>
 <!-- Execution details -->
 <div v-else-if="currentExecution" class="grid gap-6 lg:grid-cols-3">
 <!-- Left: Status & Progress -->
 <div class="space-y-6">
 <!-- Status Card -->
 <Card>
 <CardHeader class="pb-3">
 <CardTitle class="text-lg">
 状态
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div class="flex items-center gap-3">
 <div:class="cn(' rounded-lg', getStatusConfig(currentExecution.status).bg)">
 <component:is="getStatusConfig(currentExecution.status).icon":class="cn(
 'w-5 ',
 getStatusConfig(currentExecution.status).color,
 getStatusConfig(currentExecution.status).animate && 'animate-spin',
 )"
 />
 </div>
 <div>
 <div class="font-medium">
 {{ getStatusConfig(currentExecution.status).label }}
 </div>
 <div class="text-sm text-muted-foreground">
 {{ duration }}
 </div>
 </div>
 </div>
 <div class="space-y-2">
 <div class="flex justify-between text-sm">
 <span class="text-muted-foreground">进度</span>
 <span class="font-medium">{{ Math.round(progress) }}%</span>
 </div>
 <Progress:model-value="progress" class="" />
 </div>
 <Separator />
 <div class="grid grid-cols-2 gap-4 text-sm">
 <div>
 <div class="text-muted-foreground">
 总节点数
 </div>
 <div class="font-medium">
 {{ currentExecution.total_nodes }}
 </div>
 </div>
 <div>
 <div class="text-muted-foreground">
 已完成
 </div>
 <div class="font-medium text-green-600">
 {{ currentExecution.completed_nodes }}
 </div>
 </div>
 <div>
 <div class="text-muted-foreground">
 失败
 </div>
 <div class="font-medium text-red-600">
 {{ currentExecution.failed_nodes }}
 </div>
 </div>
 <div>
 <div class="text-muted-foreground">
 已跳过
 </div>
 <div class="font-medium text-gray-500">
 {{ currentExecution.skipped_nodes }}
 </div>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- Trigger Info -->
 <Card>
 <CardHeader class="pb-3">
 <CardTitle class="text-lg">
 触发器
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-2 text-sm">
 <div class="flex justify-between">
 <span class="text-muted-foreground">类型</span>
 <Badge variant="outline" class="capitalize">
 {{ currentExecution.trigger_type }}
 </Badge>
 </div>
 <div class="flex justify-between">
 <span class="text-muted-foreground">触发者</span>
 <span>{{ currentExecution.triggered_by_name || '系统' }}</span>
 </div>
 <div class="flex justify-between">
 <span class="text-muted-foreground">开始时间</span>
 <span>{{ formatTime(currentExecution.started_at) }}</span>
 </div>
 <div v-if="currentExecution.completed_at" class="flex justify-between">
 <span class="text-muted-foreground">完成时间</span>
 <span>{{ formatTime(currentExecution.completed_at) }}</span>
 </div>
 </CardContent>
 </Card>
 <!-- Error Message -->
 <Card v-if="currentExecution.error_message" class="border-destructive">
 <CardHeader class="pb-3">
 <CardTitle class="text-lg text-destructive">
 错误
 </CardTitle>
 </CardHeader>
 <CardContent>
 <p class="text-sm text-destructive">
 {{ currentExecution.error_message }}
 </p>
 </CardContent>
 </Card>
 </div>
 <!-- Right: Node Executions -->
 <div class="lg:col-span-2">
 <Card class="h-full">
 <CardHeader class="pb-3">
 <CardTitle class="text-lg">
 节点执行
 </CardTitle>
 <CardDescription>点击节点查看详情</CardDescription>
 </CardHeader>
 <CardContent>
 <ScrollArea class="h-[600px] pr-4">
 <div class="space-y-3">
 <div
 v-for="nodeExec in currentExecution.node_executions":key="nodeExec.id":class="cn(
 ' rounded-lg border cursor-pointer transition-colors',
 selectedNodeExecution?.id === nodeExec.id
 ? 'border-primary bg-primary/5': 'hover:bg-muted/50',
 )"
 @click="selectedNodeExecution = nodeExec"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div:class="cn('.5 rounded-md', getStatusConfig(nodeExec.status).bg)">
 <component:is="getStatusConfig(nodeExec.status).icon":class="cn(
 'w-4 ',
 getStatusConfig(nodeExec.status).color,
 getStatusConfig(nodeExec.status).animate && 'animate-spin',
 )"
 />
 </div>
 <div>
 <div class="font-medium">
 {{ nodeExec.node_name }}
 </div>
 <div class="text-xs text-muted-foreground">
 {{ nodeExec.node_type }}
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <Badge
 v-if="nodeExec.status === 'pending' && nodeExec.node_type === 'manual_trigger'"
 variant="outline"
 class="border-primary text-primary cursor-pointer hover:bg-primary/10"
 @click.stop="openTriggerDialog(nodeExec)"
 >
 <Zap class="w-3 mr-1" />
 触发
 </Badge>
 <Badge
 v-if="nodeExec.status === 'waiting_approval'"
 variant="outline"
 class="border-orange-500 text-orange-500"
 @click.stop="openApprovalDialog(nodeExec)"
 >
 审核
 </Badge>
 <span class="text-xs text-muted-foreground">
 {{ formatTime(nodeExec.started_at) }}
 </span>
 </div>
 </div>
 <!-- Expanded details -->
 <div v-if="selectedNodeExecution?.id === nodeExec.id" class="mt-4 space-y-3">
 <Separator />
 <!-- Error message -->
 <div v-if="nodeExec.error_message" class=" rounded bg-destructive/10 text-sm text-destructive">
 {{ nodeExec.error_message }}
 </div>
 <!-- Debug Panel (container interactions) -->
 <NodeDebugPanel
 v-if="['running', 'waiting_event', 'completed', 'failed'].includes(nodeExec.status)":node-execution-id="nodeExec.id":output-data="nodeExec.output_data":node-status="nodeExec.status"
 @answered="store.fetchExecution(executionId)"
 />
 <!-- Input/Output data -->
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <div class="text-xs font-medium text-muted-foreground mb-2">
 输入
 </div>
 <pre class=" rounded bg-muted text-xs overflow-auto max-">{{ JSON.stringify(nodeExec.input_data, null, 2) }}</pre>
 </div>
 <div>
 <div class="text-xs font-medium text-muted-foreground mb-2">
 输出
 </div>
 <pre class=" rounded bg-muted text-xs overflow-auto max-">{{ JSON.stringify(nodeExec.output_data, null, 2) }}</pre>
 </div>
 </div>
 <!-- Container logs -->
 <div v-if="nodeExec.container_logs">
 <div class="text-xs font-medium text-muted-foreground mb-2">
 日志
 </div>
 <pre class=" rounded bg-black text-green-400 text-xs overflow-auto max- font-mono">{{ nodeExec.container_logs }}</pre>
 </div>
 <!-- Approval action -->
 <div v-if="nodeExec.status === 'waiting_approval'" class="flex gap-2">
 <Button size="sm" @click.stop="openApprovalDialog(nodeExec)">
 <CheckCircle class="w-4 mr-2" />
 批准
 </Button>
 <Button size="sm" variant="destructive" @click.stop="openApprovalDialog(nodeExec)">
 <XCircle class="w-4 mr-2" />
 拒绝
 </Button>
 </div>
 <!-- Manual trigger action -->
 <div v-if="nodeExec.status === 'pending' && nodeExec.node_type === 'manual_trigger'" class="flex gap-2">
 <Button size="sm" @click.stop="openTriggerDialog(nodeExec)">
 <Zap class="w-4 mr-2" />
 触发执行
 </Button>
 </div>
 </div>
 </div>
 </div>
 </ScrollArea>
 </CardContent>
 </Card>
 </div>
 </div>
 <!-- Approval Dialog -->
 <Dialog v-model:open="approvalDialogOpen">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>审核: {{ selectedNodeExecution?.node_name }}</DialogTitle>
 <DialogDescription>
 请审核此节点的执行结果并选择批准或拒绝。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4">
 <!-- Display data -->
 <div v-if="selectedNodeExecution?.approval_data?.display_data" class=" rounded bg-muted">
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
 <XCircle class="w-4 mr-2" />
 拒绝
 </Button>
 <Button:disabled="approving" @click="handleApprove">
 <CheckCircle class="w-4 mr-2" />
 批准
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 <!-- Manual Trigger Dialog -->
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
 <Zap class="w-4 mr-2" />
 触发
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 </div>
</template>
