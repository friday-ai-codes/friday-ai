<script setup lang="ts">
import type { TriggerLogDetail, TriggerLogStatus } from '~/api/logs'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { getTriggerLog } from '~/api/logs'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Separator } from '~/components/ui/separator'
const route = useRoute('/logs/webhooks/[id]')
const router = useRouter
const { error: showError, success } = useToast
const { copy } = useClipboard
const logId = computed( => route.params.id)
useHead({
 title: computed( => `Webhook 日志 - Friday AI`),
})
// 加载数据
const loading = ref(true)
const log = ref<TriggerLogDetail | null>(null)
onMounted(async => {
 try {
 log.value = await getTriggerLog(logId.value)
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
async function copyJson {
 if (!log.value)
 return
 await copy(JSON.stringify(log.value.webhook_raw_request_parsed, null, 2))
 success('复制成功', 'JSON 已复制到剪贴板')
}
</script>
<template>
 <div class="space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/logs" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回日志列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 日志详情 -->
 <template v-else-if="log">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div class="space-y-2">
 <h1 class="text-2xl font-bold">
 Webhook 日志
 </h1>
 <div class="flex items-center gap-3">
 <Badge:variant="getStatusVariant(log.status)">
 {{ getStatusLabel(log.status) }}
 </Badge>
 <span v-if="log.event_type" class="text-muted-foreground">
 {{ log.event_type }}
 </span>
 </div>
 </div>
 <Button variant="outline" @click="copyJson">
 <span class="icon-[lucide--copy] mr-2" />
 复制 JSON
 </Button>
 </div>
 <!-- 基本信息卡片 -->
 <Card>
 <CardHeader>
 <CardTitle>基本信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <label class="text-sm text-muted-foreground">日志 ID</label>
 <p class="font-mono text-sm">
 {{ log.id }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">创建时间</label>
 <p class="text-sm">
 {{ formatDate(log.created_at) }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <label class="text-sm text-muted-foreground">事件 UUID</label>
 <p class="font-mono text-sm">
 {{ log.event_uuid || '-' }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">事件类型</label>
 <p class="font-mono text-sm">
 {{ log.event_type || '-' }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="grid gap-4 md:grid-cols-2">
 <div>
 <label class="text-sm text-muted-foreground">项目 ID</label>
 <p class="font-mono text-sm">
 {{ log.project_id || '-' }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">日志 ID</label>
 <p class="font-mono text-sm">
 {{ log.id }}
 </p>
 </div>
 </div>
 <Separator v-if="log.error_message" />
 <div v-if="log.error_message">
 <label class="text-sm text-muted-foreground">错误信息</label>
 <p class="text-sm text-destructive">
 {{ log.error_message }}
 </p>
 </div>
 </CardContent>
 </Card>
 <!-- 原始请求卡片 -->
 <Card>
 <CardHeader>
 <CardTitle>原始请求数据</CardTitle>
 <CardDescription>
 飞书 Webhook 发送的完整 JSON 请求体
 </CardDescription>
 </CardHeader>
 <CardContent>
 <div class="bg-muted rounded-lg overflow-auto max-h-[600px]">
 <pre class="text-sm font-mono whitespace-pre-wrap">{{ JSON.stringify(log.webhook_raw_request_parsed, null, 2) }}</pre>
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
 action-label="返回列表"
 @action="router.push('/logs')"
 />
 </div>
</template>
