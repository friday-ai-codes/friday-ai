<script setup lang="ts">
/**
 * ExecutionHistoryCard - 紧凑单行执行历史卡片
 *
 * 显示：状态图标 + 触发时间 + 总耗时 + 触发类型
 * 用于 ExecutionHistoryList 中的每条记录。
 */
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import ExecutionStatusBadge from './ExecutionStatusBadge.vue'
interface Props {
 execution: {
 id: string
 status: string
 trigger_type: string
 duration: number | null
 created_at: string
 }
}
const props = defineProps<Props>
defineEmits<{
 click:
 retry: [executionId: string]
}>
const formattedTime = computed( => {
 return new Date(props.execution.created_at).toLocaleString('zh-CN', {
 month: 'short',
 day: 'numeric',
 hour: '2-digit',
 minute: '2-digit',
 })
})
const formattedDuration = computed( => {
 if (!props.execution.duration) return '-'
 const seconds = Math.round(props.execution.duration)
 if (seconds < 60) return `${seconds}s`
 const minutes = Math.floor(seconds / 60)
 const remainingSeconds = seconds % 60
 return `${minutes}m ${remainingSeconds}s`
})
const triggerTypeLabel = computed( => {
 const labels: Record<string, string> = {
 manual: '手动',
 webhook: 'Webhook',
 schedule: '定时',
 event: '事件',
 api: 'API',
 }
 return labels[props.execution.trigger_type] || props.execution.trigger_type
})
const canRetry = computed( =>
 ['failed', 'cancelled'].includes(props.execution.status),
)
</script>
<template>
 <div
 class="flex items-center gap-3 px-3 py-2 rounded-xl bg-card/70 backdrop-blur-sm border border-border/50 hover:border-primary/30 hover:bg-muted/30 transition-all cursor-pointer group"
 @click="$emit('click')"
 >
 <ExecutionStatusBadge:status="execution.status":show-label="false" size="sm" />
 <span class="text-sm flex-1 truncate">{{ formattedTime }}</span>
 <span class="text-xs text-muted-foreground tabular-nums">{{ formattedDuration }}</span>
 <Badge variant="outline" class="text-[10px] shrink-0">
 {{ triggerTypeLabel }}
 </Badge>
 <Button
 v-if="canRetry"
 variant="ghost"
 size="icon"
 class=" w-6 text-muted-foreground hover:text-primary shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
 title="重试"
 @click.stop="$emit('retry', execution.id)"
 >
 <span class="icon-[lucide--rotate-ccw] w-3.5 .5" />
 </Button>
 </div>
</template>
