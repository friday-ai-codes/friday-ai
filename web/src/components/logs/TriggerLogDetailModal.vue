<script setup lang="ts">
import type { TriggerLogDetail, TriggerLogStatus } from '~/api/logs'
import { VueFinalModal } from 'vue-final-modal'
import { getTriggerLog } from '~/api/logs'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Separator } from '~/components/ui/separator'
interface Props {
 logId: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 confirm:
 cancel:
 closed:
}>
const { error: showError, success } = useToast
// 加载数据
const loading = ref(true)
const log = ref<TriggerLogDetail | null>(null)
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
async function copyJson(data: Record<string, unknown> | null, label: string) {
 if (!data)
 return
 try {
 await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
 success('复制成功', `${label} 已复制到剪贴板`)
 }
 catch {
 showError('复制失败', '无法复制到剪贴板')
 }
}
function handleClose {
 emit('cancel')
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-4xl w-full mx-4 max-h-[90vh]"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-cyan-500/10">
 <span class="icon-[lucide--file-text] text-xl text-cyan-500" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
 触发日志详情
 </h3>
 <div v-if="log" class="flex items-center gap-2 mt-1">
 <Badge:variant="getStatusVariant(log.status)">
 {{ getStatusLabel(log.status) }}
 </Badge>
 <span class="text-sm text-muted-foreground">{{ log.event_type }}</span>
 </div>
 </div>
 </div>
 <button
 type="button"
 class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
 @click="handleClose"
 >
 <svg class="w-5 " fill="none" stroke="currentColor" viewBox="0 0 24 24">
 <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
 </svg>
 </button>
 </div>
 <!-- Body -->
 <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4">
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="3" />
 <!-- 日志详情 -->
 <template v-else-if="log">
 <!-- 基本信息卡片 -->
 <Card>
 <CardHeader class="pb-3">
 <CardTitle class="text-base">基本信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-3">
 <div class="grid gap-3 md:grid-cols-2">
 <div>
 <label class="text-xs text-muted-foreground">日志 ID</label>
 <p class="font-mono text-sm">
 {{ log.id }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">创建时间</label>
 <p class="text-sm">
 {{ formatDate(log.created_at) }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="grid gap-3 md:grid-cols-2">
 <div>
 <label class="text-xs text-muted-foreground">事件 UUID</label>
 <p class="font-mono text-sm truncate":title="log.event_uuid || undefined">
 {{ log.event_uuid || '-' }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">工作项 ID</label>
 <p class="font-mono text-sm">
 {{ log.work_item_id || '-' }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="grid gap-3 md:grid-cols-2">
 <div>
 <label class="text-xs text-muted-foreground">项目 ID</label>
 <p class="font-mono text-sm">
 {{ log.project_id || '-' }}
 </p>
 </div>
 <div v-if="log.error_message">
 <label class="text-xs text-muted-foreground">错误信息</label>
 <p class="text-sm text-destructive">
 {{ log.error_message }}
 </p>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- Webhook 原始请求卡片 -->
 <Card v-if="log.webhook_raw_request_parsed">
 <CardHeader class="pb-3">
 <div class="flex items-center justify-between">
 <div>
 <CardTitle class="text-base">Webhook 原始请求</CardTitle>
 <CardDescription class="text-xs">
 飞书 Webhook 发送的完整 JSON 请求体
 </CardDescription>
 </div>
 <Button variant="outline" size="sm" @click="copyJson(log.webhook_raw_request_parsed, 'Webhook 请求')">
 <span class="icon-[lucide--copy] mr-1" />
 复制
 </Button>
 </div>
 </CardHeader>
 <CardContent>
 <div class="bg-muted rounded-lg overflow-auto max-h-[300px]">
 <pre class="text-xs font-mono whitespace-pre-wrap">{{ JSON.stringify(log.webhook_raw_request_parsed, null, 2) }}</pre>
 </div>
 </CardContent>
 </Card>
 <!-- 工作项原始响应卡片 -->
 <Card v-if="log.work_item_raw_response_parsed">
 <CardHeader class="pb-3">
 <div class="flex items-center justify-between">
 <div>
 <CardTitle class="text-base">工作项原始响应</CardTitle>
 <CardDescription class="text-xs">
 飞书 API 返回的工作项详情
 </CardDescription>
 </div>
 <Button variant="outline" size="sm" @click="copyJson(log.work_item_raw_response_parsed, '工作项响应')">
 <span class="icon-[lucide--copy] mr-1" />
 复制
 </Button>
 </div>
 </CardHeader>
 <CardContent>
 <div class="bg-muted rounded-lg overflow-auto max-h-[300px]">
 <pre class="text-xs font-mono whitespace-pre-wrap">{{ JSON.stringify(log.work_item_raw_response_parsed, null, 2) }}</pre>
 </div>
 </CardContent>
 </Card>
 </template>
 <!-- 日志不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="日志不存在"
 description="未找到该日志记录，可能已被删除"
 />
 </div>
 <!-- Footer -->
 <div class="flex justify-end px-6 py-4 border-t border-gray-200 dark:border-gray-700 shrink-0">
 <Button variant="outline" @click="handleClose">
 关闭
 </Button>
 </div>
 </VueFinalModal>
</template>
