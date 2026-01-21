<script setup lang="ts">
import type { TriggerLogDetail, TriggerLogStatus } from '~/api/logs'
import { getTriggerLogRaw } from '~/api/logs'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import JsonHighlighter from './JsonHighlighter.vue'
import KeyFieldsCard from './KeyFieldsCard.vue'
const props = defineProps<{
 log: TriggerLogDetail
 getProjectName?: (projectId: string | null) => string
}>
// 原始数据
const webhookRaw = ref<Record<string, unknown> | null>(null)
const workItemRaw = ref<Record<string, unknown> | null>(null)
const rawLoading = ref(false)
const rawLoaded = ref(false)
// 折叠状态
const webhookExpanded = ref(false)
const workItemExpanded = ref(false)
// 加载原始数据
async function loadRawData {
 if (rawLoaded.value) return
 rawLoading.value = true
 try {
 const data = await getTriggerLogRaw(props.log.id)
 webhookRaw.value = data.webhook_raw
 workItemRaw.value = data.work_item_raw
 rawLoaded.value = true
 }
 catch (e) {
 console.error('Failed to load raw data:', e)
 }
 finally {
 rawLoading.value = false
 }
}
// 当展开任一原始数据时加载
watch([webhookExpanded, workItemExpanded], ([webhook, workItem]) => {
 if ((webhook || workItem) && !rawLoaded.value) {
 loadRawData
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
 const date = new Date(dateStr)
 return date.toLocaleString('zh-CN', {
 year: 'numeric',
 month: '2-digit',
 day: '2-digit',
 hour: '2-digit',
 minute: '2-digit',
 second: '2-digit',
 })
}
</script>
<template>
 <div class="space-y-6">
 <!-- 基本信息 -->
 <Card>
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--info] w-5" />
 基本信息
 </CardTitle>
 </CardHeader>
 <CardContent>
 <dl class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
 <div>
 <dt class="text-sm font-medium text-muted-foreground">
 时间
 </dt>
 <dd class="mt-1">
 {{ formatDate(log.created_at) }}
 </dd>
 </div>
 <div>
 <dt class="text-sm font-medium text-muted-foreground">
 事件类型
 </dt>
 <dd class="mt-1">
 {{ log.event_type || '-' }}
 </dd>
 </div>
 <div>
 <dt class="text-sm font-medium text-muted-foreground">
 状态
 </dt>
 <dd class="mt-1">
 <Badge:variant="getStatusVariant(log.status)">
 {{ getStatusLabel(log.status) }}
 </Badge>
 </dd>
 </div>
 <div>
 <dt class="text-sm font-medium text-muted-foreground">
 项目
 </dt>
 <dd class="mt-1">
 {{ getProjectName?.(log.project_id) || log.project_id || '-' }}
 </dd>
 </div>
 <div>
 <dt class="text-sm font-medium text-muted-foreground">
 工作项 ID
 </dt>
 <dd class="mt-1">
 {{ log.work_item_id || '-' }}
 </dd>
 </div>
 <div>
 <dt class="text-sm font-medium text-muted-foreground">
 事件 UUID
 </dt>
 <dd class="mt-1 font-mono text-sm">
 {{ log.event_uuid || '-' }}
 </dd>
 </div>
 </dl>
 <!-- 错误信息 -->
 <div v-if="log.error_message" class="mt-4 rounded-md border border-destructive/50 bg-destructive/10 ">
 <p class="text-sm font-medium text-destructive">
 错误信息
 </p>
 <p class="mt-1 text-sm">
 {{ log.error_message }}
 </p>
 </div>
 </CardContent>
 </Card>
 <!-- 关键字段 -->
 <KeyFieldsCard:prd-url="log.prd_url":description="log.description":tech-doc-url="log.tech_doc_url"
 />
 <!-- 原始数据 -->
 <Card>
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--code] w-5" />
 原始数据
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <!-- Webhook 请求 -->
 <Collapsible v-model:open="webhookExpanded">
 <CollapsibleTrigger as-child>
 <Button variant="outline" class="w-full justify-between">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--webhook] w-4" />
 Webhook 请求
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform":class="{ 'rotate-180': webhookExpanded }"
 />
 </Button>
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-2">
 <div v-if="rawLoading" class="flex items-center justify-center ">
 <span class="icon-[lucide--loader-2] w-5 animate-spin" />
 <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
 </div>
 <JsonHighlighter v-else:json="webhookRaw" />
 </CollapsibleContent>
 </Collapsible>
 <!-- 工作项详情 -->
 <Collapsible v-model:open="workItemExpanded">
 <CollapsibleTrigger as-child>
 <Button variant="outline" class="w-full justify-between">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--file-text] w-4" />
 工作项详情
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform":class="{ 'rotate-180': workItemExpanded }"
 />
 </Button>
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-2">
 <div v-if="rawLoading" class="flex items-center justify-center ">
 <span class="icon-[lucide--loader-2] w-5 animate-spin" />
 <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
 </div>
 <JsonHighlighter v-else:json="workItemRaw" />
 </CollapsibleContent>
 </Collapsible>
 </CardContent>
 </Card>
 </div>
</template>
