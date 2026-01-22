<script setup lang="ts">
import type { TriggerLogDetail, TriggerLogStatus } from '~/api/logs'
import { VueFinalModal } from 'vue-final-modal'
import { deleteTriggerLog, getTriggerLog, retryTriggerLog } from '~/api/logs'
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
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
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
const { error: showError, success } = useToast
// 加载数据
const loading = ref(true)
const log = ref<TriggerLogDetail | null>(null)
// 操作状态
const retrying = ref(false)
const deleting = ref(false)
const showDeleteConfirm = ref(false)
const activeTab = ref('webhook')
onMounted(async => {
 try {
 log.value = await getTriggerLog(props.logId)
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取日志详情')
 }
 finally {
 loading.value = false
 }
})
// 获取状态颜色
function getStatusVariant(status: TriggerLogStatus): 'default' | 'secondary' | 'destructive' | 'outline' {
 switch (status) {
 case 'accepted':
 return 'default'
 case 'ignored':
 return 'secondary'
 case 'error':
 return 'destructive'
 case 'duplicate':
 return 'outline'
 default:
 return 'outline'
 }
}
// 获取状态标签
function getStatusLabel(status: TriggerLogStatus): string {
 switch (status) {
 case 'accepted':
 return '已接受'
 case 'ignored':
 return '已忽略'
 case 'error':
 return '错误'
 case 'duplicate':
 return '重复'
 default:
 return status
 }
}
// 格式化日期
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 复制 JSON 到剪贴板
async function copyCurrentTab {
 if (!log.value)
 return
 const data = activeTab.value === 'webhook'
 ? log.value.webhook_raw_request_parsed: log.value.work_item_raw_response_parsed
 if (!data) {
 showError('复制失败', '暂无数据')
 return
 }
 try {
 await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
 success('复制成功', '已复制到剪贴板')
 }
 catch {
 showError('复制失败', '无法复制到剪贴板')
 }
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
 catch (e) {
 showError('重试失败', e instanceof Error ? e.message: '无法重试')
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
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除')
 }
 finally {
 deleting.value = false
 }
}
function handleClose {
 emit('cancel')
}
// 检查是否为有效链接
function isValidUrl(url: string): boolean {
 if (!url)
 return false
 try {
 new URL(url)
 return true
 }
 catch {
 return false
 }
}
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
 <div class="absolute -top-20 -right-20 w-40 bg-gradient-to-br from-cyan-500/20 to-blue-500/30 rounded-full blur-3xl" />
 <div class="absolute top-10 -left-10 w-32 bg-gradient-to-tr from-violet-500/20 to-purple-500/10 rounded-full blur-3xl" />
 </div>
 <div class="flex items-start justify-between border-b border-border/50">
 <div class="flex items-center gap-4">
 <div class=" rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/10">
 <span class="icon-[lucide--file-text] text-2xl text-cyan-500" />
 </div>
 <div>
 <h3 class="text-xl font-semibold">
 {{ log.work_item_name || '未命名工作项' }}
 </h3>
 <div class="flex items-center gap-2 mt-1">
 <Badge:variant="getStatusVariant(log.status)">
 {{ getStatusLabel(log.status) }}
 </Badge>
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
 <div class="flex-1 overflow-y-auto space-y-6">
 <!-- 工作项内容 -->
 <div class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50">
 <div class=" rounded-lg bg-gradient-to-br from-violet-500/20 to-purple-500/10">
 <span class="icon-[lucide--file-code] text-lg text-violet-500" />
 </div>
 <h4 class="font-semibold">工作项内容</h4>
 </div>
 <div class=" space-y-4">
 <!-- 描述 -->
 <div v-if="log.description">
 <label class="text-xs text-muted-foreground uppercase tracking-wide">描述</label>
 <p class="mt-1 text-sm whitespace-pre-wrap">{{ log.description }}</p>
 </div>
 <!-- 文档链接 -->
 <div class="grid gap-3 sm:grid-cols-2">
 <a
 v-if="log.prd_url && isValidUrl(log.prd_url)":href="log.prd_url"
 target="_blank"
 class="group flex items-center gap-3 rounded-xl bg-muted/50 hover:bg-muted transition-colors"
 >
 <div class=" rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 text-white">
 <span class="icon-[lucide--file-text]" />
 </div>
 <div class="flex-1 min-w-0">
 <div class="font-medium">需求文档</div>
 <div class="text-xs text-muted-foreground truncate">{{ log.prd_url }}</div>
 </div>
 <span class="icon-[lucide--external-link] text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </a>
 <a
 v-if="log.tech_doc_url && isValidUrl(log.tech_doc_url)":href="log.tech_doc_url"
 target="_blank"
 class="group flex items-center gap-3 rounded-xl bg-muted/50 hover:bg-muted transition-colors"
 >
 <div class=" rounded-lg bg-gradient-to-br from-emerald-500 to-teal-400 text-white">
 <span class="icon-[lucide--code-2]" />
 </div>
 <div class="flex-1 min-w-0">
 <div class="font-medium">技术方案</div>
 <div class="text-xs text-muted-foreground truncate">{{ log.tech_doc_url }}</div>
 </div>
 <span class="icon-[lucide--external-link] text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </a>
 </div>
 <!-- 无文档链接时的提示 -->
 <div v-if="!log.description && !log.prd_url && !log.tech_doc_url" class="text-center py-4 text-muted-foreground">
 暂无工作项内容
 </div>
 <!-- 元信息 -->
 <div class="grid gap-2 sm:grid-cols-3 pt-3 border-t border-border/50">
 <div>
 <label class="text-xs text-muted-foreground">工作项 ID</label>
 <p class="font-mono text-sm">{{ log.work_item_id || '-' }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">工作项类型</label>
 <p class="text-sm">{{ log.work_item_type || '-' }}</p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">创建时间</label>
 <p class="text-sm">{{ formatDate(log.created_at) }}</p>
 </div>
 </div>
 <!-- 错误信息 -->
 <div v-if="log.error_message" class="rounded-xl border border-destructive/50 bg-destructive/10 ">
 <div class="flex items-center gap-2 text-destructive font-medium">
 <span class="icon-[lucide--alert-circle]" />
 错误信息
 </div>
 <p class="mt-1 text-sm">{{ log.error_message }}</p>
 </div>
 </div>
 </div>
 <!-- 原始数据 Tabs -->
 <div class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <Tabs v-model="activeTab" default-value="webhook" class="w-full">
 <div class="flex items-center justify-between px-4 pt-4">
 <TabsList class="bg-muted/50">
 <TabsTrigger value="webhook" class="data-[state=active]:bg-card">
 <span class="icon-[lucide--webhook] mr-2" />
 Webhook 请求
 </TabsTrigger>
 <TabsTrigger value="workitem" class="data-[state=active]:bg-card">
 <span class="icon-[lucide--file-json] mr-2" />
 工作项响应
 </TabsTrigger>
 </TabsList>
 <Button variant="ghost" size="sm" @click="copyCurrentTab">
 <span class="icon-[lucide--copy] mr-1" />
 复制
 </Button>
 </div>
 <TabsContent value="webhook" class=" pt-2">
 <div class="rounded-xl bg-muted/30 overflow-hidden max-h-[300px] overflow-y-auto">
 <JsonHighlighter
 v-if="log.webhook_raw_request_parsed":json="log.webhook_raw_request_parsed"
 />
 <div v-else class=" text-center text-muted-foreground">
 暂无数据
 </div>
 </div>
 </TabsContent>
 <TabsContent value="workitem" class=" pt-2">
 <div class="rounded-xl bg-muted/30 overflow-hidden max-h-[300px] overflow-y-auto">
 <JsonHighlighter
 v-if="log.work_item_raw_response_parsed":json="log.work_item_raw_response_parsed"
 />
 <div v-else class=" text-center text-muted-foreground">
 暂无数据
 </div>
 </div>
 </TabsContent>
 </Tabs>
 </div>
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
 <AlertDialogCancel:disabled="deleting">取消</AlertDialogCancel>
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
