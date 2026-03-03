<script setup lang="ts">
/**
 * NodeOverviewTab — 抽屉概览标签页
 *
 * 展示节点基本信息、状态、时间线、瓶颈标识和错误详情。
 */
import { computed } from 'vue'
import { getNodeVisual } from '~/components/workflow/editor/nodes/nodeVisuals'
import { useNodeStyle } from '~/components/workflow/editor/nodes/composables/useNodeStyle'
import type { NodeExecution } from '~/stores/useExecutionsStore'
import Badge from '~/components/ui/badge/Badge.vue'
import {
 CheckCircle, XCircle, Clock, Loader2, Pause,
 Square, UserCheck, Hourglass, PauseCircle, SkipForward,
 AlarmClockOff,
} from 'lucide-vue-next'
const props = defineProps<{
 nodeExecution: NodeExecution
 bottleneckInfo?: { level: string, rank: number, durationPercent: number } | null
}>
const visual = computed( => getNodeVisual(props.nodeExecution.node_type))
const style = computed( => useNodeStyle(visual.value.color).value)
/** 状态配置映射 */
const statusMap: Record<string, { icon: any, color: string, label: string }> = {
 pending: { icon: Clock, color: 'text-gray-500', label: '等待中' },
 running: { icon: Loader2, color: 'text-blue-500', label: '运行中' },
 completed: { icon: CheckCircle, color: 'text-green-500', label: '已完成' },
 failed: { icon: XCircle, color: 'text-red-500', label: '失败' },
 paused: { icon: Pause, color: 'text-yellow-500', label: '已暂停' },
 cancelled: { icon: Square, color: 'text-gray-500', label: '已取消' },
 waiting_approval: { icon: UserCheck, color: 'text-orange-500', label: '待审批' },
 waiting_event: { icon: Hourglass, color: 'text-indigo-500', label: '等待操作' },
 suspended: { icon: PauseCircle, color: 'text-indigo-500', label: '已挂起' },
 skipped: { icon: SkipForward, color: 'text-gray-400', label: '已跳过' },
 timeout: { icon: AlarmClockOff, color: 'text-red-500', label: '超时' },
}
const statusInfo = computed( => statusMap[props.nodeExecution.status] ?? statusMap.pending)
function formatDuration(seconds: number | null): string {
 if (seconds == null) return '-'
 if (seconds < 60) return `${Math.round(seconds)}s`
 if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
 return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}
function formatTime(isoStr: string | null): string {
 if (!isoStr) return '-'
 return new Date(isoStr).toLocaleString('zh-CN')
}
</script>
<template>
 <div class="space-y-4">
 <!-- 瓶颈标识 -->
 <div v-if="bottleneckInfo" class="flex items-center gap-2">
 <Badge
 variant="outline":class="bottleneckInfo.level === 'critical'
 ? 'border-red-400/50 text-red-500 bg-red-50 dark:bg-red-900/20': 'border-yellow-400/50 text-yellow-600 bg-yellow-50 dark:bg-yellow-900/20'"
 >
 {{ bottleneckInfo.level === 'critical' ? `瓶颈 #${bottleneckInfo.rank}`: `瓶颈 #${bottleneckInfo.rank}` }}
 · 占总耗时 {{ bottleneckInfo.durationPercent }}%
 </Badge>
 </div>
 <!-- 节点信息卡片 -->
 <div class="bg-card/60 backdrop-blur-sm border border-border/50 rounded-xl space-y-3">
 <!-- 节点类型 + 图标 -->
 <div class="flex items-center gap-3">
 <div:class="['bg-gradient-to-br rounded-lg ', style.iconBg]">
 <component:is="visual.icon" class="w-5 ":class="style.iconColor" />
 </div>
 <div>
 <div class="text-sm font-medium text-foreground">{{ nodeExecution.node_name }}</div>
 <div class="text-xs text-muted-foreground">{{ nodeExecution.node_type }}</div>
 </div>
 </div>
 <!-- 信息行 -->
 <div class="grid grid-cols-2 gap-2 text-sm">
 <div class="text-muted-foreground">状态</div>
 <div class="flex items-center gap-1.5">
 <component:is="statusInfo.icon" class="w-4 ":class="statusInfo.color" />
 <span:class="statusInfo.color">{{ statusInfo.label }}</span>
 </div>
 <div class="text-muted-foreground">开始时间</div>
 <div>{{ formatTime(nodeExecution.started_at) }}</div>
 <div class="text-muted-foreground">完成时间</div>
 <div>{{ formatTime(nodeExecution.completed_at) }}</div>
 <div class="text-muted-foreground">耗时</div>
 <div class="tabular-nums font-medium">{{ formatDuration(nodeExecution.duration) }}</div>
 <div v-if="nodeExecution.attempt > 1" class="text-muted-foreground">重试次数</div>
 <div v-if="nodeExecution.attempt > 1">{{ nodeExecution.attempt - 1 }}</div>
 </div>
 </div>
 <!-- 错误信息 -->
 <div
 v-if="nodeExecution.error_message"
 class="bg-red-50 dark:bg-red-900/20 border border-red-200/50 dark:border-red-800/50 rounded-xl space-y-2"
 >
 <div class="text-sm font-medium text-red-600 dark:text-red-400">错误信息</div>
 <pre class="text-xs text-red-700 dark:text-red-300 whitespace-pre-wrap break-words">{{ nodeExecution.error_message }}</pre>
 <details v-if="nodeExecution.error_traceback" class="mt-2">
 <summary class="text-xs text-red-500 cursor-pointer hover:text-red-600">查看堆栈</summary>
 <pre class="mt-1 text-xs text-red-600/80 dark:text-red-400/80 whitespace-pre-wrap break-words overflow-auto max-">{{ nodeExecution.error_traceback }}</pre>
 </details>
 </div>
 </div>
</template>
