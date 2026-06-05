<script setup lang="ts">
import type { TriggerLogDetail } from '~/api/logs'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Button } from '~/components/ui/button'

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible'
import JsonHighlighter from './JsonHighlighter.vue'
import KeyFieldsCard from './KeyFieldsCard.vue'

defineProps<{
  log: TriggerLogDetail
  getSpaceName?: (spaceId: string | null) => string
}>()

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
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
        <h3 class="text-sm font-semibold">
          <span class="icon-[lucide--info] h-5 w-5" />
          基本信息
        </h3>
      </div>
      <div class="p-5 space-y-4">
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
              <StatusBadge type="triggerLog" :status="log.status" />
            </dd>
          </div>
          <div>
            <dt class="text-sm font-medium text-muted-foreground">
              空间
            </dt>
            <dd class="mt-1">
              {{ getSpaceName?.(log.space_id) || log.space_id || '-' }}
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
        <div v-if="log.error_message" class="mt-4 rounded-md border border-destructive/50 bg-destructive/10 p-3">
          <p class="text-sm font-medium text-destructive">
            错误信息
          </p>
          <p class="mt-1 text-sm">
            {{ log.error_message }}
          </p>
        </div>
      </div>
    </div>

    <!-- 关键字段 -->
    <KeyFieldsCard
      :prd-url="log.prd_url"
      :description="log.description"
      :tech-doc-url="log.tech_doc_url"
    />

    <!-- 原始数据 -->
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
        <h3 class="text-sm font-semibold">
          <span class="icon-[lucide--code] h-5 w-5" />
          原始数据
        </h3>
      </div>
      <div class="p-5 space-y-4">
        <!-- Webhook 请求 -->
        <Collapsible v-model:open="webhookExpanded">
          <CollapsibleTrigger as-child>
            <Button variant="outline" class="w-full justify-between">
              <span class="flex items-center gap-2">
                <span class="icon-[lucide--webhook] h-4 w-4" />
                Webhook 请求
              </span>
              <span
                class="icon-[lucide--chevron-down] h-4 w-4 transition-transform"
                :class="{ 'rotate-180': webhookExpanded }"
              />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent class="mt-2">
            <JsonHighlighter :json="log.webhook_raw_request_parsed" />
          </CollapsibleContent>
        </Collapsible>

        <!-- 工作项响应 -->
        <Collapsible v-model:open="workItemExpanded">
          <CollapsibleTrigger as-child>
            <Button variant="outline" class="w-full justify-between">
              <span class="flex items-center gap-2">
                <span class="icon-[lucide--file-text] h-4 w-4" />
                工作项响应
              </span>
              <span
                class="icon-[lucide--chevron-down] h-4 w-4 transition-transform"
                :class="{ 'rotate-180': workItemExpanded }"
              />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent class="mt-2">
            <JsonHighlighter :json="log.work_item_raw_response_parsed" />
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  </div>
</template>
