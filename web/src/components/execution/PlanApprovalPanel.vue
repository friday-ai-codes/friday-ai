<script setup lang="ts">
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Separator } from '~/components/ui/separator'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useExecutionsStore } from '~/stores/useExecutionsStore'
/**
 * PlanApprovalPanel - AI 方案审批专用面板
 *
 * 功能：
 * - 分块折叠展示方案内容（title, summary, tasks, risks, assumptions）
 * - waiting_event 状态下显示通过/驳回按钮
 * - 驳回弹窗输入理由
 * - 审批完成后显示只读状态卡片
 */
interface Props {
 nodeExecution: {
 id: string
 status: string
 node_type: string
 approval_data?: Record<string, any>
 output_data?: Record<string, any>
 }
}
const props = defineProps<Props>
const emit = defineEmits<{
 actionComplete:
}>
const store = useExecutionsStore
const { handleError } = useErrorHandler
const { success, error: showError } = useToast
// 方案数据提取
const planData = computed( => {
 const data = props.nodeExecution.approval_data || props.nodeExecution.output_data || {}
 return data.plan || data || null
})
const planTitle = computed( => planData.value?.title || '技术方案')
const planSummary = computed( => planData.value?.summary || '')
const planTasks = computed(: Record<string, any> => planData.value?.tasks || )
const planRisks = computed(: (string | Record<string, any>) => planData.value?.risks || )
const planAssumptions = computed(: (string | Record<string, any>) => planData.value?.assumptions || )
const documentUrl = computed( => {
 const data = props.nodeExecution.approval_data || props.nodeExecution.output_data || {}
 return data.document_url || ''
})
// 状态判断
const isWaiting = computed( => props.nodeExecution.status === 'waiting_event')
const isCompleted = computed( => props.nodeExecution.status === 'completed')
const approvalResult = computed( => {
 if (!isCompleted.value)
 return null
 const output = props.nodeExecution.output_data || {}
 const handle = output._next_handle
 if (handle === 'approved')
 return 'approved'
 if (handle === 'rejected')
 return 'rejected'
 return null
})
const rejectReason = computed( => {
 return props.nodeExecution.output_data?.reject_reason || ''
})
// 交互状态
const rejectDialogOpen = ref(false)
const rejectReasonInput = ref('')
const submitting = ref(false)
// 折叠面板状态
const tasksOpen = ref(false)
const risksOpen = ref(false)
const assumptionsOpen = ref(false)
async function handleApprove {
 submitting.value = true
 try {
 await store.approveNode(props.nodeExecution.id, '')
 success('方案已通过')
 emit('actionComplete')
 }
 catch (e: unknown) {
 handleError(e, '审批')
 }
 finally {
 submitting.value = false
 }
}
function openRejectDialog {
 rejectReasonInput.value = ''
 rejectDialogOpen.value = true
}
async function handleReject {
 if (!rejectReasonInput.value.trim) {
 showError('请输入驳回理由')
 return
 }
 submitting.value = true
 try {
 await store.rejectNode(props.nodeExecution.id, rejectReasonInput.value)
 rejectDialogOpen.value = false
 success('方案已驳回')
 emit('actionComplete')
 }
 catch (e: unknown) {
 handleError(e, '驳回')
 }
 finally {
 submitting.value = false
 }
}
</script>
<template>
 <div class="card card overflow-hidden">
 <!-- Header -->
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div class="bg-primary/10 rounded-lg ">
 <span class="icon-[lucide--check-circle] w-5 text-amber-500" />
 </div>
 <div>
 <h3 class="text-sm font-semibold">
 {{ planTitle }}
 </h3>
 <a
 v-if="documentUrl":href="documentUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="text-xs text-primary hover:underline flex items-center gap-1 mt-0.5"
 >
 <span class="icon-[lucide--external-link] w-3 " />
 查看完整文档
 </a>
 </div>
 </div>
 <!-- Completed status badge -->
 <Badge
 v-if="isCompleted && approvalResult === 'approved'"
 class="bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
 >
 <span class="icon-[lucide--check] w-3 mr-1" />
 已通过
 </Badge>
 <Badge
 v-else-if="isCompleted && approvalResult === 'rejected'"
 class="bg-red-500/10 text-red-600 border-red-500/20"
 >
 <span class="icon-[lucide--x] w-3 mr-1" />
 已驳回
 </Badge>
 <Badge
 v-else-if="isWaiting"
 class="bg-amber-500/10 text-amber-600 border-amber-500/20 animate-pulse"
 >
 <span class="icon-[lucide--hourglass] w-3 mr-1" />
 待审批
 </Badge>
 </div>
 </div>
 <div class=" space-y-4">
 <!-- Summary (always visible) -->
 <div v-if="planSummary" class="space-y-1.5">
 <div class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
 <span class="icon-[lucide--align-left] w-3.5 .5" />
 摘要
 </div>
 <p class="text-sm leading-relaxed whitespace-pre-wrap">
 {{ planSummary }}
 </p>
 </div>
 <Separator v-if="planSummary" />
 <!-- Tasks (collapsible) -->
 <Collapsible v-if="planTasks.length > 0" v-model:open="tasksOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--list-checks] w-4 text-violet-500" />
 任务列表
 <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
 {{ planTasks.length }}
 </Badge>
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform duration-200":class="{ 'rotate-180': tasksOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-2 pt-2">
 <div
 v-for="(task, index) in planTasks":key="index"
 class="rounded-xl border border-border/40 hover:border-primary/30 hover:shadow-sm transition-all"
 >
 <div class="flex items-start gap-2">
 <span class="mt-0.5 flex w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/10 text-violet-600 text-[10px] font-bold">
 {{ index + 1 }}
 </span>
 <div class="space-y-1 flex-1 min-w-0">
 <div class="text-sm font-medium">
 {{ task.name || task.title || `Task ${index + 1}` }}
 </div>
 <p v-if="task.description" class="text-xs text-muted-foreground leading-relaxed">
 {{ task.description }}
 </p>
 <div v-if="task.repository" class="flex items-center gap-1 text-[10px] text-muted-foreground">
 <span class="icon-[lucide--git-branch] w-3 " />
 {{ task.repository }}
 </div>
 <div v-if="task.files && task.files.length > 0" class="flex flex-wrap gap-1 pt-1">
 <span
 v-for="file in task.files.slice(0, 5)":key="file"
 class="px-1.5 py-0.5 rounded bg-muted text-[10px] font-mono text-muted-foreground"
 >
 {{ file }}
 </span>
 <span
 v-if="task.files.length > 5"
 class="px-1.5 py-0.5 rounded bg-muted text-[10px] text-muted-foreground"
 >
 +{{ task.files.length - 5 }} more
 </span>
 </div>
 </div>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Risks (collapsible) -->
 <Collapsible v-if="planRisks.length > 0" v-model:open="risksOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--alert-triangle] w-4 text-amber-500" />
 风险
 <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
 {{ planRisks.length }}
 </Badge>
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform duration-200":class="{ 'rotate-180': risksOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-1.5 pt-2">
 <div
 v-for="(risk, index) in planRisks":key="index"
 class="flex items-start gap-2 text-sm rounded-lg bg-amber-500/5 border border-amber-500/10"
 >
 <span class="icon-[lucide--alert-triangle] w-3.5 .5 text-amber-500 mt-0.5 shrink-0" />
 <span>{{ typeof risk === 'string' ? risk: risk.description || risk.name || JSON.stringify(risk) }}</span>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Assumptions (collapsible) -->
 <Collapsible v-if="planAssumptions.length > 0" v-model:open="assumptionsOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors group">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--lightbulb] w-4 text-primary" />
 假设
 <Badge variant="secondary" class="text-[10px] px-1.5 py-0">
 {{ planAssumptions.length }}
 </Badge>
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform duration-200":class="{ 'rotate-180': assumptionsOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-1.5 pt-2">
 <div
 v-for="(assumption, index) in planAssumptions":key="index"
 class="flex items-start gap-2 text-sm rounded-lg bg-primary/5 border border-primary/10"
 >
 <span class="icon-[lucide--lightbulb] w-3.5 .5 text-primary mt-0.5 shrink-0" />
 <span>{{ typeof assumption === 'string' ? assumption: assumption.description || assumption.name || JSON.stringify(assumption) }}</span>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Reject reason (readonly, when completed and rejected) -->
 <div
 v-if="isCompleted && approvalResult === 'rejected' && rejectReason"
 class=" rounded-xl bg-red-500/5 border border-red-500/20"
 >
 <div class="text-xs font-medium text-red-600 mb-1 flex items-center gap-1.5">
 <span class="icon-[lucide--message-circle] w-3.5 .5" />
 驳回理由
 </div>
 <p class="text-sm text-red-600/80">
 {{ rejectReason }}
 </p>
 </div>
 <Separator v-if="isWaiting" />
 <!-- Action buttons (only when waiting) -->
 <div v-if="isWaiting" class="flex items-center gap-3 pt-1">
 <Button:disabled="submitting"
 class="flex-1 hover:from-emerald-600 hover:to-teal-500 text-white shadow-md hover:shadow-lg transition-all"
 @click="handleApprove"
 >
 <span class="icon-[lucide--check] w-4 mr-2" />
 通过
 </Button>
 <Button:disabled="submitting"
 variant="destructive"
 class="flex-1 shadow-md hover:shadow-lg transition-all"
 @click="openRejectDialog"
 >
 <span class="icon-[lucide--x] w-4 mr-2" />
 驳回
 </Button>
 </div>
 </div>
 </div>
 <!-- Reject Dialog -->
 <Dialog v-model:open="rejectDialogOpen">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>驳回方案</DialogTitle>
 <DialogDescription>
 请输入驳回理由，将通过飞书通知方案作者。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-3">
 <Textarea
 v-model="rejectReasonInput"
 placeholder="请输入驳回理由..."
 class="min-"
 />
 </div>
 <DialogFooter>
 <Button variant="outline" @click="rejectDialogOpen = false">
 取消
 </Button>
 <Button
 variant="destructive":disabled="submitting || !rejectReasonInput.trim"
 @click="handleReject"
 >
 <span class="icon-[lucide--x] w-4 mr-2" />
 确认驳回
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
