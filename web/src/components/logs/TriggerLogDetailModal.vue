<script setup lang="ts">
import type { TriggerLogDetail } from '~/api/logs'
import { VueFinalModal } from 'vue-final-modal'
import { deleteTriggerLog, getTriggerLog, retryTriggerLog } from '~/api/logs'
import { useErrorHandler } from '~/composables/useErrorHandler'
import StatusBadge from '~/components/common/StatusBadge.vue'
import {
 AlertDialog,
 AlertDialogAction,
 AlertDialogCancel,
 AlertDialogContent,
 AlertDialogDescription,
 AlertDialogFooter,
 AlertDialogHeader,
 AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import JsonHighlighter from './JsonHighlighter.vue'
interface Props {
 logId: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 confirm:
 cancel:
 closed:
 refresh:
}>
const { handleError } = useErrorHandler
const { success } = useToast
// 加载数据
const loading = ref(true)
const log = ref<TriggerLogDetail | null>(null)
// 操作状态
const retrying = ref(false)
const deleting = ref(false)
const showDeleteConfirm = ref(false)
const rawExpanded = ref(false)
onMounted(async => {
 try {
 log.value = await getTriggerLog(props.logId)
 }
 catch (e: unknown) {
 handleError(e, '加载日志详情')
 }
 finally {
 loading.value = false
 }
})
// 格式化日期
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 格式化时间戳（毫秒）
function formatTimestamp(ts: number) {
 return new Date(ts).toLocaleString('zh-CN')
}
// 重试
async function handleRetry {
 if (!log.value)
 return
 retrying.value = true
 try {
 await retryTriggerLog(log.value.id)
 success('重试成功', '已重新处理该触发事件')
 emit('refresh')
 }
 catch (e: unknown) {
 handleError(e, '重试')
 }
 finally {
 retrying.value = false
 }
}
// 删除
async function handleDelete {
 if (!log.value)
 return
 deleting.value = true
 try {
 await deleteTriggerLog(log.value.id)
 success('删除成功', '日志已删除')
 showDeleteConfirm.value = false
 emit('refresh')
 handleClose
 }
 catch (e: unknown) {
 handleError(e, '删除')
 }
 finally {
 deleting.value = false
 }
}
function handleClose {
 emit('cancel')
}
// 从 webhook 原始数据中提取 payload
const webhookPayload = computed( => {
 const parsed = log.value?.webhook_raw_request_parsed
 if (!parsed || typeof parsed !== 'object')
 return null
 return (parsed as Record<string, unknown>).payload as Record<string, unknown> | undefined
})
// 从 webhook 原始数据中提取 header
const webhookHeader = computed( => {
 const parsed = log.value?.webhook_raw_request_parsed
 if (!parsed || typeof parsed !== 'object')
 return null
 return (parsed as Record<string, unknown>).header as Record<string, unknown> | undefined
})
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-xl border border-border/50 max-w-4xl w-full mx-4 max-h-[90vh] overflow-hidden"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- 加载状态 -->
 <div v-if="loading" class="">
 <LoadingState variant="skeleton":count="3" />
 </div>
 <!-- 日志不存在 -->
 <div v-else-if="!log" class="">
 <EmptyState
 icon="lucide--help-circle"
 title="日志不存在"
 description="未找到该日志记录，可能已被删除"
 />
 </div>
 <!-- 日志详情 -->
 <template v-else>
 <!-- Header with Glassmorphism -->
 <div class="relative overflow-hidden shrink-0">
 <!-- Background gradient decoration -->
 <div class="absolute inset-0 -z-10">
 <div class="absolute -top-20 -right-20 w-40 bg-gradient-to-br from-primary/20 to-primary/30 rounded-full blur-3xl" />
 <div class="absolute top-10 -left-10 w-32 bg-gradient-to-tr from-violet-500/20 to-purple-500/10 rounded-full blur-3xl" />
 </div>
 <div class="flex items-start justify-between border-b border-border/50">
 <div class="flex items-center gap-4">
 <div class=" rounded-xl bg-gradient-to-br from-primary/20 to-primary/10">
 <span class="icon-[lucide--file-text] text-2xl text-cyan-500" />
 </div>
 <div>
 <h3 class="text-xl font-semibold">
 {{ log.work_item_name || '未命名工作项' }}
 </h3>
 <div class="flex items-center gap-2 mt-1">
 <StatusBadge type="triggerLog":status="log.status" />
 <span class="text-sm text-muted-foreground">{{ log.event_type }}</span>
 </div>
 </div>
 </div>
 <!-- Action buttons -->
 <div class="flex items-center gap-2">
 <Button variant="outline" size="sm":disabled="retrying" @click="handleRetry">
 <span class="icon-[lucide--refresh-cw] mr-1":class="{ 'animate-spin': retrying }" />
 重试
 </Button>
 <Button variant="outline" size="sm" class="text-destructive hover:text-destructive" @click="showDeleteConfirm = true">
 <span class="icon-[lucide--trash-2] mr-1" />
 删除
 </Button>
 <button
 type="button"
 class=" text-muted-foreground hover:text-foreground transition-colors rounded-lg hover:bg-muted/50"
 @click="handleClose"
 >
 <span class="icon-[lucide--x] text-lg" />
 </button>
 </div>
 </div>
 </div>
 <!-- Body -->
 <div class="flex-1 overflow-y-auto space-y-4">
 <!-- Webhook 事件信息 -->
 <div class="rounded-xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <div class="flex items-center gap-2 px-3 py-2 border-b border-border/50">
 <div class=".5 rounded-md bg-gradient-to-br from-violet-500/20 to-purple-500/10">
 <span class="icon-[lucide--webhook] text-sm text-violet-500" />
 </div>
 <h4 class="text-sm font-medium">
 事件信息
 </h4>
 </div>
 <div class="px-3 py-2 space-y-2">
 <!-- 基本信息网格 -->
 <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-2">
 <!-- 工作项 ID -->
 <div>
 <label class="text-xs text-muted-foreground">工作项 ID</label>
 <p class="font-mono text-sm">
 {{ webhookPayload?.id || log.work_item_id || '-' }}
 </p>
 </div>
 <!-- 工作项类型 -->
 <div>
 <label class="text-xs text-muted-foreground">类型</label>
 <p class="text-sm">
 {{ webhookPayload?.work_item_type_key || log.work_item_type || '-' }}
 </p>
 </div>
 <!-- 项目 -->
 <div>
 <label class="text-xs text-muted-foreground">项目</label>
 <p class="text-sm truncate":title="webhookPayload?.project_key as string">
 {{ webhookPayload?.project_simple_name || '-' }}
 </p>
 </div>
 <!-- 操作人 -->
 <div>
 <label class="text-xs text-muted-foreground">操作人</label>
 <p class="font-mono text-sm truncate">
 {{ webhookHeader?.operator || webhookPayload?.updated_by || '-' }}
 </p>
 </div>
 <!-- 事件时间 -->
 <div>
 <label class="text-xs text-muted-foreground">事件时间</label>
 <p class="text-sm">
 {{ webhookPayload?.updated_at ? formatTimestamp(webhookPayload.updated_at as number): formatDate(log.created_at) }}
 </p>
 </div>
 <!-- 事件 UUID -->
 <div class="col-span-2 sm:col-span-1">
 <label class="text-xs text-muted-foreground">事件 UUID</label>
 <p class="font-mono text-xs text-muted-foreground truncate">
 {{ webhookHeader?.uuid || log.event_uuid || '-' }}
 </p>
 </div>
 <!-- 状态变更（仅 WorkitemStatusEvent） -->
 <div v-if="webhookPayload?.pre_sub_stage && webhookPayload?.cur_sub_stage" class="col-span-2">
 <label class="text-xs text-muted-foreground">状态变更</label>
 <div class="flex items-center gap-1.5 mt-0.5">
 <code class="px-1.5 py-0.5 rounded bg-muted text-xs">{{ webhookPayload.pre_sub_stage }}</code>
 <span class="icon-[lucide--arrow-right] text-xs text-muted-foreground" />
 <code class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-xs">{{ webhookPayload.cur_sub_stage }}</code>
 </div>
 </div>
 </div>
 <!-- 错误信息 -->
 <div v-if="log.error_message" class="rounded-lg border border-destructive/50 bg-destructive/10 mt-2">
 <div class="flex items-center gap-1.5 text-destructive text-sm font-medium">
 <span class="icon-[lucide--alert-circle] text-sm" />
 错误
 </div>
 <p class="text-xs mt-0.5">
 {{ log.error_message }}
 </p>
 </div>
 </div>
 </div>
 <!-- 关联的工作流执行 -->
 <div v-if="log.workflow_executions?.length" class="rounded-xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <div class="flex items-center gap-2 px-3 py-2 border-b border-border/50">
 <div class=".5 rounded-md bg-gradient-to-br from-emerald-500/20 to-teal-500/10">
 <span class="icon-[lucide--play-circle] text-sm text-emerald-500" />
 </div>
 <h4 class="text-sm font-medium">
 关联执行
 </h4>
 <span class="text-xs text-muted-foreground">({{ log.workflow_executions.length }})</span>
 </div>
 <div class="divide-y divide-border/50">
 <RouterLink
 v-for="exec in log.workflow_executions":key="exec.id":to="`/executions/${exec.id}`"
 class="flex items-center justify-between px-3 py-2 hover:bg-muted/30 transition-colors group"
 >
 <div class="flex items-center gap-2 min-w-0">
 <span
 class="w-2 rounded-full shrink-0":class="{
 'bg-emerald-500': exec.status === 'completed',
 'bg-primary animate-pulse': exec.status === 'running',
 'bg-amber-500': exec.status === 'pending',
 'bg-red-500': exec.status === 'failed',
 'bg-gray-400': exec.status === 'cancelled',
 }"
 />
 <span class="text-sm truncate">{{ exec.workflow_name }}</span>
 </div>
 <div class="flex items-center gap-2 shrink-0">
 <span class="text-xs text-muted-foreground">{{ formatDate(exec.created_at) }}</span>
 <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </div>
 </RouterLink>
 </div>
 </div>
 <!-- 原始 Webhook 数据（可折叠） -->
 <Collapsible v-model:open="rawExpanded">
 <div class="rounded-xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <CollapsibleTrigger as-child>
 <button
 type="button"
 class="flex items-center justify-between w-full px-3 py-2 hover:bg-muted/30 transition-colors"
 >
 <div class="flex items-center gap-2">
 <div class=".5 rounded-md bg-gradient-to-br from-amber-500/20 to-orange-500/10">
 <span class="icon-[lucide--code] text-sm text-amber-500" />
 </div>
 <h4 class="text-sm font-medium">
 原始数据
 </h4>
 </div>
 <span
 class="icon-[lucide--chevron-down] text-sm text-muted-foreground transition-transform":class="{ 'rotate-180': rawExpanded }"
 />
 </button>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="border-t border-border/50">
 <div class="max-h-[240px] overflow-y-auto">
 <JsonHighlighter
 v-if="log.webhook_raw_request_parsed":json="log.webhook_raw_request_parsed"
 />
 <div v-else class=" text-center text-muted-foreground text-sm">
 暂无数据
 </div>
 </div>
 </div>
 </CollapsibleContent>
 </div>
 </Collapsible>
 </div>
 </template>
 <!-- 删除确认弹窗 -->
 <AlertDialog v-model:open="showDeleteConfirm">
 <AlertDialogContent>
 <AlertDialogHeader>
 <AlertDialogTitle>确认删除</AlertDialogTitle>
 <AlertDialogDescription>
 确定要删除这条触发日志吗？此操作无法撤销。
 </AlertDialogDescription>
 </AlertDialogHeader>
 <AlertDialogFooter>
 <AlertDialogCancel:disabled="deleting">
 取消
 </AlertDialogCancel>
 <AlertDialogAction
 class="bg-destructive text-destructive-foreground hover:bg-destructive/90":disabled="deleting"
 @click="handleDelete"
 >
 {{ deleting ? '删除中...': '删除' }}
 </AlertDialogAction>
 </AlertDialogFooter>
 </AlertDialogContent>
 </AlertDialog>
 </VueFinalModal>
</template>
