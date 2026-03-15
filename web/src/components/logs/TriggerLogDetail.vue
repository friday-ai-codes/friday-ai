<script setup lang="ts">
import type { TriggerLogDetail, TriggerLogStatus } from '~/api/logs'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import StatusBadge from '~/components/common/StatusBadge.vue'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import JsonHighlighter from './JsonHighlighter.vue'
import KeyFieldsCard from './KeyFieldsCard.vue'
defineProps<{
 log: TriggerLogDetail
 getProjectName?: (projectId: string | null) => string
}>
// 折叠状态
const webhookExpanded = ref(false)
const workItemExpanded = ref(false)
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
 <StatusBadge type="triggerLog":status="log.status" />
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
 <JsonHighlighter:json="log.webhook_raw_request_parsed" />
 </CollapsibleContent>
 </Collapsible>
 <!-- 工作项响应 -->
 <Collapsible v-model:open="workItemExpanded">
 <CollapsibleTrigger as-child>
 <Button variant="outline" class="w-full justify-between">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--file-text] w-4" />
 工作项响应
 </span>
 <span
 class="icon-[lucide--chevron-down] w-4 transition-transform":class="{ 'rotate-180': workItemExpanded }"
 />
 </Button>
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-2">
 <JsonHighlighter:json="log.work_item_raw_response_parsed" />
 </CollapsibleContent>
 </Collapsible>
 </CardContent>
 </Card>
 </div>
</template>
