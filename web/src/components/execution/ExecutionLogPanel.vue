<script setup lang="ts">
import type { ExecutionLogEntry } from '~/types/execution'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { ScrollArea } from '~/components/ui/scroll-area'

const props = defineProps<{
  logs: ExecutionLogEntry[]
}>()

function getLogColorClass(level: string): string {
  switch (level) {
    case 'INFO':
      return 'text-slate-400'
    case 'WARN':
      return 'text-amber-500'
    case 'ERROR':
      return 'text-red-500'
    default:
      return 'text-slate-400'
  }
}

function getLogIconClass(level: string): string {
  switch (level) {
    case 'INFO':
      return 'icon-[lucide--info]'
    case 'WARN':
      return 'icon-[lucide--alert-triangle]'
    case 'ERROR':
      return 'icon-[lucide--circle-x]'
    default:
      return 'icon-[lucide--minus]'
  }
}

function getLogBorderClass(level: string): string {
  switch (level) {
    case 'WARN':
      return 'border-amber-500/30 bg-amber-500/5'
    case 'ERROR':
      return 'border-red-500/30 bg-red-500/5'
    default:
      return 'border-border/20'
  }
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
}

function formatContext(context: Record<string, any> | null | undefined): string {
  if (!context)
    return ''
  try {
    return JSON.stringify(context, null, 2)
  }
  catch {
    return String(context)
  }
}
</script>

<template>
  <ScrollArea class="h-full">
    <div class="px-6 py-4 space-y-1">
      <div
        v-for="(log, index) in logs"
        :key="index"
        class="border-b last:border-b-0 py-2"
        :class="getLogBorderClass(log.level)"
      >
        <Collapsible>
          <CollapsibleTrigger class="w-full">
            <div class="flex items-start gap-2 text-left w-full">
              <!-- 级别图标 -->
              <span
                class="shrink-0 w-4 h-4 mt-0.5"
                :class="[getLogIconClass(log.level), getLogColorClass(log.level)]"
              />
              <!-- 时间戳 -->
              <span class="text-xs text-muted-foreground shrink-0 font-mono tabular-nums">
                {{ formatTimestamp(log.timestamp) }}
              </span>
              <!-- 消息 -->
              <span class="text-sm flex-1" :class="getLogColorClass(log.level)">
                {{ log.message }}
              </span>
              <!-- 展开指示器（有上下文时显示） -->
              <span
                v-if="log.context && Object.keys(log.context).length > 0"
                class="icon-[lucide--chevron-down] w-4 h-4 text-muted-foreground shrink-0 transition-transform"
              />
            </div>
          </CollapsibleTrigger>

          <!-- 上下文详情（可展开） -->
          <CollapsibleContent v-if="log.context && Object.keys(log.context).length > 0">
            <div class="mt-2 ml-10 bg-muted/40 rounded-lg p-2">
              <pre class="text-xs font-mono text-muted-foreground whitespace-pre-wrap">{{ formatContext(log.context) }}</pre>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  </ScrollArea>
</template>
