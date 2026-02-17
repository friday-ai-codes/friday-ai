<script setup lang="ts">
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { useTimeoutPoll } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import AICodeReviewPanel from '~/components/execution/AICodeReviewPanel.vue'
import AICodingPanel from '~/components/execution/AICodingPanel.vue'
import NodeDebugPanel from '~/components/execution/NodeDebugPanel.vue'
import PlanApprovalPanel from '~/components/execution/PlanApprovalPanel.vue'
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
const route = useRoute
const router = useRouter
const executionId = computed( => (route.params as { id: string }).id)
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
// Polling with useTimeoutPoll - auto cleanup on unmount
function isActiveStatus(status?: string) {
 return ['running', 'pending', 'queued', 'paused', 'waiting_approval', 'waiting_event', 'suspended'].includes(status || '')
}
const { pause: stopPolling, resume: startPolling } = useTimeoutPoll(
 async => {
 if ((route.params as { id: string }).id === executionId.value) {
 await store.fetchExecution(executionId.value)
 if (!isActiveStatus(currentExecution.value?.status)) {
 stopPolling
 }
 }
 else {
 stopPolling
 }
 },
 5000,
 { immediate: false },
)
onMounted(async => {
 await store.fetchExecution(executionId.value)
 if (isActiveStatus(currentExecution.value?.status)) {
 startPolling
 }
})
watch( => currentExecution.value?.status, (newStatus) => {
 if (isActiveStatus(newStatus)) {
 startPolling
 }
 else {
 stopPolling
 }
})
// Status helpers
const statusConfig: Record<string, { icon: string, color: string, bg: string, label: string, animate?: boolean }> = {
 pending: { icon: 'lucide--clock', color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800', label: '等待中' },
 running: { icon: 'lucide--loader-2', color: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900/30', label: '运行中', animate: true },
 completed: { icon: 'lucide--check-circle', color: 'text-green-500', bg: 'bg-green-100 dark:bg-green-900/30', label: '已完成' },
 failed: { icon: 'lucide--x-circle', color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30', label: '失败' },
 paused: { icon: 'lucide--pause', color: 'text-yellow-500', bg: 'bg-yellow-100 dark:bg-yellow-900/30', label: '已暂停' },
 cancelled: { icon: 'lucide--square', color: 'text-gray-500', bg: 'bg-gray-100 dark:bg-gray-800', label: '已取消' },
 waiting_approval: { icon: 'lucide--user-check', color: 'text-orange-500', bg: 'bg-orange-100 dark:bg-orange-900/30', label: '待审批' },
 waiting_event: { icon: 'lucide--hourglass', color: 'text-indigo-500', bg: 'bg-indigo-100 dark:bg-indigo-900/30', label: '等待操作', animate: true },
 suspended: { icon: 'lucide--pause-circle', color: 'text-indigo-500', bg: 'bg-indigo-100 dark:bg-indigo-900/30', label: '已挂起' },
 skipped: { icon: 'lucide--skip-forward', color: 'text-gray-400', bg: 'bg-gray-100 dark:bg-gray-800', label: '已跳过' },
 timeout: { icon: 'lucide--alarm-clock-off', color: 'text-red-500', bg: 'bg-red-100 dark:bg-red-900/30', label: '超时' },
}
const getStatusConfig = (status: string) => statusConfig[status] || statusConfig.pending
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
 <div class="relative space-y-6 max-w-[1400px] mx-auto pb-10">
 <!-- Background decorations -->
 <div class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <!-- Header -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-4">
 <Button variant="ghost" size="icon" @click="router.push('/executions')">
 <span class="icon-[lucide--arrow-left] w-5 " />
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
 <span class="icon-[lucide--pause] w-4 mr-2" />
 暂停
 </Button>
 <Button
 v-if="currentExecution?.status === 'paused'"
 variant="outline"
 size="sm"
 @click="handleResume"
 >
 <span class="icon-[lucide--play] w-4 mr-2" />
 继续
 </Button>
 <Button
 v-if="['running', 'paused', 'pending', 'waiting_approval', 'waiting_event', 'suspended'].includes(currentExecution?.status || '')"
 variant="destructive"
 size="sm"
 @click="handleCancel"
 >
 <span class="icon-[lucide--square] w-4 mr-2" />
 取消
 </Button>
 <Button
 v-if="currentExecution?.status === 'failed' || currentExecution?.status === 'cancelled'"
 variant="default"
 size="sm"
 @click="handleRetry"
 >
 <span class="icon-[lucide--rotate-ccw] w-4 mr-2" />
 重试
 </Button>
 <Button variant="ghost" size="icon" @click="store.fetchExecution(executionId)">
 <span class="icon-[lucide--refresh-cw] w-4 " />
 </Button>
 </div>
 </div>
 <!-- Loading state -->
 <div v-if="loading && !currentExecution" class="flex justify-center py-12">
 <span class="icon-[lucide--loader-2] w-8 animate-spin text-primary" />
 </div>
 <!-- Error state -->
 <Card v-else-if="error" class="border-destructive">
 <CardContent class="py-6 text-center text-destructive">
 <span class="icon-[lucide--x-circle] w-12 mx-auto mb-4" />
 <p>{{ error }}</p>
 </CardContent>
 </Card>
 <!-- Execution details -->
 <div v-else-if="currentExecution" class="grid gap-6 lg:grid-cols-3">
 <!-- Left: Status & Progress -->
 <div class="space-y-6">
 <!-- Status Card -->
 <Card class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <CardHeader class="pb-3">
 <CardTitle class="text-lg">
 状态
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div class="flex items-center gap-3">
 <div:class="cn(' rounded-lg', getStatusConfig(currentExecution.status).bg)">
 <span
 class="w-5 ":class="[
 `icon-[${getStatusConfig(currentExecution.status).icon}]`,
 getStatusConfig(currentExecution.status).color,
 getStatusConfig(currentExecution.status).animate && 'animate-spin',
 ]"
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
 <Card class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
 <CardHeader class="pb-3">
 <CardTitle class="text-lg">
 触发信息
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
 <Card v-if="currentExecution.error_message" class="border-destructive rounded-2xl">
 <CardHeader class="pb-3">
 <CardTitle class="text-lg text-destructive">
 错误信息
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
 <Card class="h-full rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50">
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
 ' rounded-xl border cursor-pointer transition-all duration-300',
 selectedNodeExecution?.id === nodeExec.id
 ? 'border-primary bg-primary/5': 'hover:bg-muted/50 hover:border-primary/30',
 )"
 @click="selectedNodeExecution = nodeExec"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div:class="cn('.5 rounded-lg', getStatusConfig(nodeExec.status).bg)">
 <span
 class="w-4 ":class="[
 `icon-[${getStatusConfig(nodeExec.status).icon}]`,
 getStatusConfig(nodeExec.status).color,
 getStatusConfig(nodeExec.status).animate && 'animate-spin',
 ]"
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
 <span class="icon-[lucide--zap] w-3 mr-1" />
 触发
 </Badge>
 <Badge
 v-if="nodeExec.status === 'waiting_approval'"
 variant="outline"
 class="border-orange-500 text-orange-500 cursor-pointer hover:bg-orange-500/10"
 @click.stop="openApprovalDialog(nodeExec)"
 >
 审核
 </Badge>
 <Badge
 v-if="nodeExec.status === 'waiting_event' && nodeExec.node_type === 'ai_plan_approval'"
 variant="outline"
 class="border-indigo-500 text-indigo-500 cursor-pointer hover:bg-indigo-500/10"
 @click.stop="selectedNodeExecution = nodeExec"
 >
 <span class="icon-[lucide--check-circle] w-3 mr-1" />
 审批
 </Badge>
 <Badge
 v-if="nodeExec.status === 'running' && nodeExec.node_type === 'ai_coding'"
 variant="outline"
 class="border-blue-500 text-blue-500 animate-pulse"
 >
 <span class="icon-[lucide--terminal] w-3 mr-1" />
 编码中
 </Badge>
 <span class="text-xs text-muted-foreground">
 {{ formatTime(nodeExec.started_at) }}
 </span>
 </div>
 </div>
 <!-- Expanded details -->
 <div v-if="selectedNodeExecution?.id === nodeExec.id" class="mt-4 space-y-3">
 <Separator />
 <!-- Plan Approval Panel (for ai_plan_approval nodes) -->
 <PlanApprovalPanel
 v-if="nodeExec.node_type === 'ai_plan_approval' && (nodeExec.status === 'waiting_event' || nodeExec.status === 'completed')":node-execution="nodeExec"
 @action-complete="store.fetchExecution(executionId)"
 />
 <!-- AI Coding Panel (for ai_coding nodes) -->
 <AICodingPanel
 v-if="nodeExec.node_type === 'ai_coding' && (nodeExec.status === 'running' || nodeExec.status === 'waiting_event' || nodeExec.status === 'completed')":node-execution="nodeExec"
 />
 <!-- AI Code Review Panel (for ai_code_review nodes) -->
 <AICodeReviewPanel
 v-else-if="nodeExec.node_type === 'ai_code_review' && (nodeExec.status === 'running' || nodeExec.status === 'completed' || nodeExec.status === 'failed')":node-execution="nodeExec"
 />
 <!-- Debug Panel (for nodes with container interactions) -->
 <NodeDebugPanel
 v-if="['running', 'waiting_event', 'completed', 'failed'].includes(nodeExec.status)":node-execution-id="nodeExec.id":output-data="nodeExec.output_data":node-status="nodeExec.status"
 @answered="store.fetchExecution(executionId)"
 />
 <!-- Error message -->
 <div v-if="nodeExec.error_message" class=" rounded-lg bg-destructive/10 text-sm text-destructive">
 {{ nodeExec.error_message }}
 </div>
 <!-- Input/Output data -->
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <div class="text-xs font-medium text-muted-foreground mb-2">
 输入
 </div>
 <pre class=" rounded-lg bg-muted text-xs overflow-auto max-">{{ JSON.stringify(nodeExec.input_data, null, 2) }}</pre>
 </div>
 <div>
 <div class="text-xs font-medium text-muted-foreground mb-2">
 输出
 </div>
 <pre class=" rounded-lg bg-muted text-xs overflow-auto max-">{{ JSON.stringify(nodeExec.output_data, null, 2) }}</pre>
 </div>
 </div>
 <!-- Container logs -->
 <div v-if="nodeExec.container_logs">
 <div class="text-xs font-medium text-muted-foreground mb-2">
 日志
 </div>
 <pre class=" rounded-lg bg-black text-green-400 text-xs overflow-auto max- font-mono">{{ nodeExec.container_logs }}</pre>
 </div>
 <!-- Approval action -->
 <div v-if="nodeExec.status === 'waiting_approval'" class="flex gap-2">
 <Button size="sm" @click.stop="openApprovalDialog(nodeExec)">
 <span class="icon-[lucide--check-circle] w-4 mr-2" />
 批准
 </Button>
 <Button size="sm" variant="destructive" @click.stop="openApprovalDialog(nodeExec)">
 <span class="icon-[lucide--x-circle] w-4 mr-2" />
 拒绝
 </Button>
 </div>
 <!-- Manual trigger action -->
 <div v-if="nodeExec.status === 'pending' && nodeExec.node_type === 'manual_trigger'" class="flex gap-2">
 <Button size="sm" @click.stop="openTriggerDialog(nodeExec)">
 <span class="icon-[lucide--zap] w-4 mr-2" />
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
 <span class="icon-[lucide--zap] w-4 mr-2" />
 触发
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 </div>
</template>
