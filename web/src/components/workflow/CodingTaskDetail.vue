<script setup lang="ts">
import type { CodingTask } from '~/types'
import { Check, ExternalLink, GitBranch, GitCommit, MessageSquare, X } from 'lucide-vue-next'
import { ref } from 'vue'
import {
 approveCodingTaskCode,
 approveCodingTaskPlan,
 rejectCodingTaskCode,
 rejectCodingTaskPlan,
} from '~/api/workflow'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import { Textarea } from '~/components/ui/textarea'
interface Props {
 task: CodingTask | null
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'close'): void
 (e: 'updated', task: CodingTask): void
}>
const feedback = ref('')
const processing = ref(false)
// 状态颜色映射
const statusColors: Record<string, string> = {
 pending: 'bg-gray-100 text-gray-700',
 planning: 'bg-blue-100 text-blue-700',
 plan_review: 'bg-yellow-100 text-yellow-700',
 executing: 'bg-blue-100 text-blue-700',
 code_review: 'bg-yellow-100 text-yellow-700',
 merged: 'bg-green-100 text-green-700',
 failed: 'bg-red-100 text-red-700',
}
// 状态中文映射
const statusLabels: Record<string, string> = {
 pending: '待执行',
 planning: '规划中',
 plan_review: '方案评审',
 executing: '执行中',
 code_review: '代码评审',
 merged: '已合并',
 failed: '失败',
}
function getStatusColor(status: string) {
 return statusColors[status] || statusColors.pending
}
function getStatusLabel(status: string): string {
 return statusLabels[status] || status
}
// 批准方案
async function handleApprovePlan {
 if (!props.task)
 return
 processing.value = true
 try {
 await approveCodingTaskPlan(props.task.id)
 emit('updated', { ...props.task, status: 'executing' })
 }
 catch (error) {
 console.error('Failed to approve plan:', error)
 }
 finally {
 processing.value = false
 }
}
// 驳回方案
async function handleRejectPlan {
 if (!props.task)
 return
 processing.value = true
 try {
 await rejectCodingTaskPlan(props.task.id, feedback.value)
 emit('updated', { ...props.task, status: 'planning' })
 feedback.value = ''
 }
 catch (error) {
 console.error('Failed to reject plan:', error)
 }
 finally {
 processing.value = false
 }
}
// 批准代码
async function handleApproveCode {
 if (!props.task)
 return
 processing.value = true
 try {
 await approveCodingTaskCode(props.task.id)
 emit('updated', { ...props.task, status: 'merged' })
 }
 catch (error) {
 console.error('Failed to approve code:', error)
 }
 finally {
 processing.value = false
 }
}
// 驳回代码
async function handleRejectCode {
 if (!props.task)
 return
 processing.value = true
 try {
 await rejectCodingTaskCode(props.task.id, feedback.value)
 emit('updated', { ...props.task, status: 'executing' })
 feedback.value = ''
 }
 catch (error) {
 console.error('Failed to reject code:', error)
 }
 finally {
 processing.value = false
 }
}
</script>
<template>
 <Card v-if="task" class="h-full flex flex-col">
 <CardHeader class="pb-3 border-b">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <GitBranch class="w-4 text-primary" />
 <CardTitle class="text-base truncate">
 {{ task.name }}
 </CardTitle>
 </div>
 <div class="flex items-center gap-2">
 <Badge:class="getStatusColor(task.status)">
 {{ getStatusLabel(task.status) }}
 </Badge>
 <Button variant="ghost" size="icon" class=" w-7" @click="emit('close')">
 <X class="w-4 " />
 </Button>
 </div>
 </div>
 </CardHeader>
 <ScrollArea class="flex-1">
 <CardContent class=" space-y-4">
 <!-- 基本信息 -->
 <div class="space-y-2">
 <h4 class="text-sm font-medium">
 任务信息
 </h4>
 <div class="grid grid-cols-2 gap-2 text-sm">
 <div class="text-muted-foreground">
 仓库
 </div>
 <div>{{ task.repository_name || '-' }}</div>
 <div class="text-muted-foreground">
 分支
 </div>
 <div>{{ task.branch_name || '-' }}</div>
 <div class="text-muted-foreground">
 重试次数
 </div>
 <div>{{ task.retry_count }}</div>
 </div>
 </div>
 <Separator />
 <!-- Git 产物 -->
 <div v-if="task.branch_name || task.commit_sha || task.pr_url" class="space-y-2">
 <h4 class="text-sm font-medium">
 Git 产物
 </h4>
 <div class="space-y-2 text-sm">
 <div v-if="task.branch_name" class="flex items-center gap-2">
 <GitBranch class="w-4 text-muted-foreground" />
 <code class="bg-secondary px-2 py-0.5 rounded">{{ task.branch_name }}</code>
 </div>
 <div v-if="task.commit_sha" class="flex items-center gap-2">
 <GitCommit class="w-4 text-muted-foreground" />
 <code class="bg-secondary px-2 py-0.5 rounded">{{ task.commit_sha.substring(0, 8) }}</code>
 </div>
 <div v-if="task.pr_url" class="flex items-center gap-2">
 <ExternalLink class="w-4 text-muted-foreground" />
 <a:href="task.pr_url"
 target="_blank"
 rel="noopener noreferrer"
 class="text-primary hover:underline"
 >
 查看 Pull Request
 </a>
 </div>
 </div>
 </div>
 <Separator v-if="task.branch_name || task.commit_sha || task.pr_url" />
 <!-- Prompt -->
 <div class="space-y-2">
 <h4 class="text-sm font-medium">
 任务 Prompt
 </h4>
 <pre class="text-xs bg-secondary rounded-md overflow-x-auto whitespace-pre-wrap">{{ task.prompt }}</pre>
 </div>
 <!-- 规划输出 -->
 <div v-if="task.plan_output" class="space-y-2">
 <h4 class="text-sm font-medium">
 规划输出
 </h4>
 <pre class="text-xs bg-secondary rounded-md overflow-x-auto whitespace-pre-wrap max-">{{ task.plan_output }}</pre>
 </div>
 <!-- 错误信息 -->
 <div v-if="task.error_message" class="space-y-2">
 <h4 class="text-sm font-medium text-destructive">
 错误信息
 </h4>
 <pre class="text-xs bg-destructive/10 text-destructive rounded-md overflow-x-auto whitespace-pre-wrap">{{ task.error_message }}</pre>
 </div>
 <!-- 人工反馈 -->
 <div v-if="task.human_feedback" class="space-y-2">
 <h4 class="text-sm font-medium flex items-center gap-2">
 <MessageSquare class="w-4 " />
 人工反馈
 </h4>
 <pre class="text-xs bg-secondary rounded-md overflow-x-auto whitespace-pre-wrap">{{ task.human_feedback }}</pre>
 </div>
 <!-- 审批操作 -->
 <div v-if="task.status === 'plan_review' || task.status === 'code_review'" class="space-y-3 pt-2">
 <Separator />
 <h4 class="text-sm font-medium">
 {{ task.status === 'plan_review' ? '方案审批': '代码审批' }}
 </h4>
 <Textarea
 v-model="feedback"
 placeholder="输入反馈意见（驳回时必填）"
 rows="2"
 />
 <div class="flex gap-2">
 <Button
 v-if="task.status === 'plan_review'"
 class="flex-1":disabled="processing"
 @click="handleApprovePlan"
 >
 <Check class="w-4 mr-1" />
 批准方案
 </Button>
 <Button
 v-if="task.status === 'plan_review'"
 variant="outline"
 class="flex-1":disabled="processing"
 @click="handleRejectPlan"
 >
 <X class="w-4 mr-1" />
 驳回
 </Button>
 <Button
 v-if="task.status === 'code_review'"
 class="flex-1":disabled="processing"
 @click="handleApproveCode"
 >
 <Check class="w-4 mr-1" />
 批准合并
 </Button>
 <Button
 v-if="task.status === 'code_review'"
 variant="outline"
 class="flex-1":disabled="processing"
 @click="handleRejectCode"
 >
 <X class="w-4 mr-1" />
 驳回
 </Button>
 </div>
 </div>
 </CardContent>
 </ScrollArea>
 </Card>
 <!-- Empty state -->
 <Card v-else class="h-full flex items-center justify-center">
 <div class="text-center text-muted-foreground">
 <GitBranch class="w-8 mx-auto mb-2 opacity-50" />
 <p>选择任务查看详情</p>
 </div>
 </Card>
</template>
