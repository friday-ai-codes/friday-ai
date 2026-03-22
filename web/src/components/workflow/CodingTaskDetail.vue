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
import StatusBadge from '~/components/common/StatusBadge.vue'
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
// 批准方案
async function handleApprovePlan {
 if (!props.task)
 return
 processing.value = true
 try {
 await approveCodingTaskPlan(props.task.id)
 emit('updated', { ...props.task, status: 'executing' })
 }
 catch {
 // intentionally ignored
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
 catch {
 // intentionally ignored
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
 catch {
 // intentionally ignored
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
 catch {
 // intentionally ignored
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
 <StatusBadge type="codingTask":status="task.status" />
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
 <!-- MR Section -->
 <div v-if="task.pr_url || task.status === 'partial_success'" class="space-y-3">
 <h4 class="text-sm font-medium flex items-center gap-2">
 <span class="icon-[lucide--git-pull-request] w-4 text-primary" />
 Merge Request
 </h4>
 <!-- MR Link Card -->
 <a
 v-if="task.pr_url":href="task.pr_url"
 target="_blank"
 rel="noopener noreferrer"
 class="block rounded-xl bg-gradient-to-r from-emerald-500/10 to-teal-500/5
 border border-emerald-200 dark:border-emerald-800
 hover:from-emerald-500/20 hover:to-teal-500/10
 transition-all duration-300 group"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-emerald-500/20">
 <span class="icon-[lucide--git-pull-request] w-5 text-emerald-600" />
 </div>
 <div>
 <p class="font-medium text-emerald-700 dark:text-emerald-400">
 查看 Merge Request
 </p>
 <p class="text-xs text-muted-foreground truncate max-w-[300px]">
 {{ task.pr_url }}
 </p>
 </div>
 </div>
 <span
 class="icon-[lucide--external-link] w-4 text-emerald-500
 group-hover:translate-x-1 transition-transform"
 />
 </div>
 <!-- Conflict warning -->
 <div
 v-if="task.mr_has_conflicts"
 class="mt-3 rounded-lg bg-amber-100 dark:bg-amber-900/30
 flex items-center gap-2"
 >
 <span class="icon-[lucide--alert-triangle] w-4 text-amber-500" />
 <span class="text-sm text-amber-700 dark:text-amber-400">
 此 MR 有合并冲突，需要人工解决
 </span>
 </div>
 </a>
 <!-- Partial success guidance -->
 <div
 v-else-if="task.status === 'partial_success'"
 class=" rounded-xl bg-amber-50 dark:bg-amber-900/20
 border border-amber-200 dark:border-amber-800"
 >
 <div class="flex items-start gap-3">
 <div class=" rounded-lg bg-amber-500/20">
 <span class="icon-[lucide--alert-triangle] w-5 text-amber-500" />
 </div>
 <div class="flex-1">
 <p class="font-medium text-amber-700 dark:text-amber-400">
 MR 创建失败
 </p>
 <p class="text-sm text-muted-foreground mt-1">
 代码已成功推送到分支，但自动创建 MR 失败。
 </p>
 <div v-if="task.branch_name" class="mt-3 rounded-lg bg-card/50">
 <p class="text-xs text-muted-foreground">
 分支名称
 </p>
 <code class="text-sm">{{ task.branch_name }}</code>
 </div>
 <p class="text-xs text-muted-foreground mt-3">
 请在 Git 平台手动创建 MR，或检查仓库 API 配置。
 </p>
 </div>
 </div>
 </div>
 </div>
 <Separator v-if="task.pr_url || task.status === 'partial_success'" />
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
