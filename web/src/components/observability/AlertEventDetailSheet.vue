<script setup lang="ts">
/**
 * 告警事件详情抽屉（UI-03 §4.1）。
 *
 * 展示完整 rule_info（metric/op/threshold/current/window_s/dimension/expr 键值表）+
 * target（维度）+ notified_channels（通道徽标）+ 起止 / 持续 / 当前值 / last_seen。
 * 原始 JSON 一律用 <pre> 文本渲染（禁 v-html，T-75-03-03）。event=null 不渲染主体。
 */
import type { AlertEventRow } from '~/api/system'
import { computed } from 'vue'
import { alertSeverityClass, alertStatusClass } from '~/components/observability/status'
import { Badge } from '~/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '~/components/ui/sheet'
import { EMPTY, formatDateTime } from './format'

const props = defineProps<{
  event: AlertEventRow | null
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const STATUS_LABEL: Record<string, string> = { firing: '进行中', resolved: '已恢复' }
const EMAIL_LABEL: Record<string, string> = {
  sent: '已发送',
  skipped: '已忽略',
  failed: '失败',
  pending: '待发送',
}

/** rule_info 键值对（保序展示；值非字符串转 JSON 文本）。 */
const ruleInfoRows = computed(() => {
  const info = props.event?.rule_info ?? {}
  return Object.entries(info).map(([key, value]) => ({
    key,
    value: typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value),
  }))
})

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  }
  catch {
    return String(value)
  }
}

function onOpenChange(v: boolean) {
  emit('update:open', v)
}
</script>

<template>
  <Sheet :open="open" @update:open="onOpenChange">
    <SheetContent class="w-full overflow-y-auto sm:max-w-md" aria-label="告警事件详情">
      <SheetHeader>
        <SheetTitle class="flex items-center gap-2">
          <span class="icon-[lucide--bell-ring] text-primary" />
          告警事件详情
        </SheetTitle>
        <SheetDescription>
          完整规则信息、触发维度与通知通道（只读，已脱敏）
        </SheetDescription>
      </SheetHeader>

      <div v-if="event" class="space-y-5 px-4 pb-6 text-sm">
        <!-- 标题 + 徽标 -->
        <div class="space-y-2">
          <h3 class="text-base font-semibold leading-snug">
            {{ event.title_zh || EMPTY }}
          </h3>
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
              :class="alertSeverityClass(event.severity)"
            >{{ event.severity }}</span>
            <span
              class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
              :class="alertStatusClass(event.status)"
            >{{ STATUS_LABEL[event.status] ?? event.status }}</span>
            <span class="font-mono text-xs text-muted-foreground">
              {{ event.rule != null ? `#${event.rule}` : `${EMPTY}（已删）` }}
            </span>
          </div>
        </div>

        <!-- 时间 / 当前值概览 -->
        <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
          <div>
            <dt class="text-xs text-muted-foreground">
              开始时间
            </dt>
            <dd class="font-mono text-xs tabular-nums">
              {{ formatDateTime(event.started_at) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              结束时间
            </dt>
            <dd class="font-mono text-xs tabular-nums">
              {{ formatDateTime(event.ended_at) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              持续时长
            </dt>
            <dd class="font-mono text-xs tabular-nums">
              {{ event.duration_s != null ? `${Math.round(event.duration_s)}s` : EMPTY }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              当前值
            </dt>
            <dd class="font-mono text-xs tabular-nums">
              {{ event.current_value ?? EMPTY }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              最近一次命中
            </dt>
            <dd class="font-mono text-xs tabular-nums">
              {{ formatDateTime(event.last_seen_at) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted-foreground">
              邮件状态
            </dt>
            <dd class="text-xs">
              {{ EMAIL_LABEL[event.email_sent] ?? event.email_sent ?? EMPTY }}
            </dd>
          </div>
        </dl>

        <!-- rule_info 键值表 -->
        <section class="space-y-2">
          <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
            <span class="icon-[lucide--sliders-horizontal]" /> 规则信息
          </h4>
          <div v-if="ruleInfoRows.length" class="overflow-hidden rounded-lg border border-border/60">
            <dl class="divide-y divide-border/50">
              <div v-for="row in ruleInfoRows" :key="row.key" class="flex gap-3 px-3 py-2">
                <dt class="w-32 shrink-0 font-mono text-xs text-muted-foreground">
                  {{ row.key }}
                </dt>
                <dd class="min-w-0 flex-1 break-all font-mono text-xs">
                  {{ row.value }}
                </dd>
              </div>
            </dl>
          </div>
          <p v-else class="text-xs text-muted-foreground">
            {{ EMPTY }}
          </p>
        </section>

        <!-- 触发维度（target） -->
        <section class="space-y-2">
          <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
            <span class="icon-[lucide--git-branch]" /> 触发维度
          </h4>
          <pre class="overflow-auto rounded-lg bg-muted/40 p-3 font-mono text-xs">{{ prettyJson(event.target) }}</pre>
        </section>

        <!-- 通知通道 -->
        <section class="space-y-2">
          <h4 class="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
            <span class="icon-[lucide--send]" /> 已通知通道
          </h4>
          <div v-if="event.notified_channels?.length" class="flex flex-wrap gap-1.5">
            <Badge v-for="ch in event.notified_channels" :key="ch" variant="info" class="text-[11px]">
              {{ ch }}
            </Badge>
          </div>
          <p v-else class="text-xs text-muted-foreground">
            未通知任何通道
          </p>
        </section>
      </div>
    </SheetContent>
  </Sheet>
</template>
