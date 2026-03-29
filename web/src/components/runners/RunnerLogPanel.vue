<script setup lang="ts">
import type { MonitorLog } from '~/composables/useRunnerMonitor'
import { getRunnerLogs } from '~/api/runners'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Checkbox } from '~/components/ui/checkbox'
const props = defineProps<{
 runnerId: string
}>
// 日志源
const { logs } = useRunnerMonitor
// 历史日志（从 REST API 加载，不污染全局 WS logs 单例）
const historyLogs = ref<MonitorLog>
const historyLoading = ref(false)
let historyIdCounter = -1
function eventTypeToMonitorLog(event: import('~/types').RunnerEvent): MonitorLog {
 let event_str: string
 let data: Record<string, unknown>
 switch (event.event_type) {
 case 'connected':
 event_str = 'runner.status_changed'
 data = { ...event.detail, status: 'online' }
 break
 case 'disconnected':
 event_str = 'runner.status_changed'
 data = { ...event.detail, status: 'offline' }
 break
 case 'heartbeat':
 event_str = 'runner.status_changed'
 data = event.detail
 break
 case 'task_assigned':
 event_str = 'task.status_changed'
 data = { ...event.detail, status: 'running' }
 break
 case 'task_completed':
 event_str = 'task.status_changed'
 data = { ...event.detail, status: 'completed' }
 break
 case 'task_failed':
 event_str = 'task.status_changed'
 data = { ...event.detail, status: 'failed' }
 break
 default:
 event_str = event.event_type
 data = event.detail
 }
 return {
 id: historyIdCounter--,
 event: event_str,
 runner_id: props.runnerId,
 data,
 timestamp: new Date(event.created_at),
 }
}
onMounted(async => {
 historyLoading.value = true
 try {
 const res = await getRunnerLogs(props.runnerId)
 historyLogs.value = res.results.map(eventTypeToMonitorLog)
 }
 catch {
 // 加载失败静默处理，不影响实时日志展示
 }
 finally {
 historyLoading.value = false
 }
})
// 折叠偏好（localStorage 持久化）
const collapsed = useStorage('runner-log-panel-collapsed', false)
type LogType = 'connection' | 'heartbeat' | 'task' | 'error'
// 过滤器
const filters = ref<Record<LogType, boolean>>({ connection: true, heartbeat: true, task: true, error: true })
const logFilterOptions: Array<{
 key: LogType
 label: string
 textClass: string
 checkboxClass: string
}> = [
 {
 key: 'connection',
 label: '连接',
 textClass: 'text-primary',
 checkboxClass: 'border-primary/60 data-[state=checked]:bg-primary data-[state=checked]:border-primary',
 },
 {
 key: 'heartbeat',
 label: '心跳',
 textClass: 'text-muted-foreground',
 checkboxClass: 'border-muted-foreground/60 data-[state=checked]:bg-muted-foreground data-[state=checked]:border-muted-foreground data-[state=checked]:text-background',
 },
 {
 key: 'task',
 label: '任务',
 textClass: 'text-violet-400',
 checkboxClass: 'border-violet-400/60 data-[state=checked]:bg-violet-500 data-[state=checked]:border-violet-500',
 },
 {
 key: 'error',
 label: '错误',
 textClass: 'text-red-400',
 checkboxClass: 'border-red-400/60 data-[state=checked]:bg-red-500 data-[state=checked]:border-red-500',
 },
]
function updateFilter(type: LogType, checked: boolean | 'indeterminate') {
 filters.value[type] = checked === true
}
// 心跳展开
const heartbeatExpanded = ref(false)
// 自动滚动
const scrollContainer = ref<HTMLElement | null>(null)
const isAtBottom = ref(true)
const newLogCount = ref(0)
function getLogType(log: MonitorLog): LogType {
 if (log.event === 'runner.status_changed') {
 if (log.data.status === 'online' || log.data.status === 'offline')
 return 'connection'
 if (log.data.current_tasks !== undefined)
 return 'heartbeat'
 }
 if (log.event === 'task.status_changed')
 return 'task'
 return 'error'
}
function getLogColor(log: MonitorLog): string {
 const type = getLogType(log)
 if (type === 'connection')
 return 'text-primary'
 if (type === 'heartbeat')
 return 'text-muted-foreground'
 if (type === 'task') {
 const status = log.data.status as string | undefined
 if (status === 'completed')
 return 'text-emerald-400'
 if (status === 'failed')
 return 'text-red-400'
 return 'text-violet-400'
 }
 return 'text-destructive'
}
function getLogIcon(log: MonitorLog): string {
 const type = getLogType(log)
 if (type === 'connection') {
 return log.data.status === 'online' ? 'icon-[lucide--wifi]': 'icon-[lucide--wifi-off]'
 }
 if (type === 'heartbeat')
 return 'icon-[lucide--heart-pulse]'
 if (type === 'task')
 return 'icon-[lucide--play-circle]'
 return 'icon-[lucide--alert-circle]'
}
function formatLogMessage(log: MonitorLog): string {
 const type = getLogType(log)
 if (type === 'connection') {
 if (log.data.status === 'online') {
 const parts = ['Runner 上线']
 if (log.data.name)
 parts.push(`${log.data.name}`)
 if (log.data.version)
 parts.push(`v${log.data.version}`)
 return parts.join(' · ')
 }
 return 'Runner 下线'
 }
 if (type === 'heartbeat') {
 const tasks = log.data.current_tasks ?? 0
 return `心跳 · 当前任务: ${tasks}`
 }
 if (type === 'task') {
 const taskId = ((log.data.task_id as string) || '').slice(0, 8)
 const status = log.data.status as string
 if (status === 'completed')
 return `任务完成: ${taskId}`
 if (status === 'failed')
 return `任务失败: ${taskId}`
 return `任务开始: ${taskId}`
 }
 return `${log.event}: ${JSON.stringify(log.data)}`
}
function formatTimestamp(date: Date): string {
 return date.toLocaleTimeString('zh-CN', { hour12: false })
}
// 过滤后的日志
const filteredLogs = computed( => {
 // 合并历史日志与实时日志，按 runnerId 过滤
 const combined = [
 ...historyLogs.value,
 ...logs.value.filter(l => l.runner_id === props.runnerId),
 ].sort((a, b) => a.timestamp.getTime - b.timestamp.getTime)
 // 按类型过滤
 let result = combined.filter((l) => {
 const type = getLogType(l)
 return filters.value[type]
 })
 // 心跳折叠：未展开时只保留最近 5 条
 if (!heartbeatExpanded.value) {
 const heartbeats: number =
 for (let i = 0; i < result.length; i++) {
 if (getLogType(result[i]) === 'heartbeat')
 heartbeats.push(i)
 }
 if (heartbeats.length > 5) {
 const toRemove = new Set(heartbeats.slice(0, heartbeats.length - 5))
 result = result.filter((_, i) => !toRemove.has(i))
 }
 }
 return result
})
// 被折叠的心跳数量
const hiddenHeartbeatCount = computed( => {
 if (heartbeatExpanded.value)
 return 0
 const combined = [
 ...historyLogs.value,
 ...logs.value.filter(l => l.runner_id === props.runnerId),
 ]
 const total = combined.filter(l => getLogType(l) === 'heartbeat').length
 return Math.max(0, total - 5)
})
// 滚动事件
function onScroll {
 const el = scrollContainer.value
 if (!el)
 return
 isAtBottom.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 30
 if (isAtBottom.value)
 newLogCount.value = 0
}
function scrollToBottom {
 const el = scrollContainer.value
 if (!el)
 return
 el.scrollTop = el.scrollHeight
 isAtBottom.value = true
 newLogCount.value = 0
}
// 监听日志变化，自动滚动或累计计数
watch( => filteredLogs.value.length, => {
 if (isAtBottom.value) {
 nextTick(scrollToBottom)
 }
 else {
 newLogCount.value++
 }
})
</script>
<template>
 <Card class="bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl">
 <CardHeader
 class="border-b border-border/50 bg-linear-to-r from-gray-500/5 to-slate-500/5 cursor-pointer select-none"
 @click="collapsed = !collapsed"
 >
 <div class="flex items-center justify-between">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--terminal] text-gray-500" />
 实时日志
 </CardTitle>
 <span
 class="w-5 transition-transform duration-200":class="collapsed ? 'icon-[lucide--chevron-down]': 'icon-[lucide--chevron-up]'"
 />
 </div>
 <!-- 过滤器 -->
 <div v-show="!collapsed" class="flex flex-wrap items-center gap-2 text-xs mt-3" @click.stop>
 <label
 v-for="option in logFilterOptions":key="option.key":for="`runner-log-filter-${option.key}`"
 class="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-2.5 py-1.5 cursor-pointer transition-colors hover:bg-muted/60"
 >
 <Checkbox:id="`runner-log-filter-${option.key}`":checked="filters[option.key]"
 class=".5 w-3.5 rounded-[4px] ring-offset-0 focus-visible:ring-1 focus-visible:ring-offset-0":class="option.checkboxClass"
 @update:checked="updateFilter(option.key, $event)"
 />
 <span class="font-medium":class="option.textClass">{{ option.label }}</span>
 </label>
 </div>
 </CardHeader>
 <CardContent v-show="!collapsed" class="">
 <div class="relative">
 <div
 ref="scrollContainer"
 class="bg-gray-950 rounded-b-2xl font-mono text-sm max- overflow-y-auto"
 @scroll="onScroll"
 >
 <!-- 空状态 -->
 <p v-if="filteredLogs.length === 0 && !historyLoading" class="text-muted-foreground text-center py-6">
 等待事件...
 </p>
 <!-- 历史日志加载中 -->
 <div v-if="historyLoading" class="text-xs text-muted-foreground px-2 py-1">
 加载历史日志…
 </div>
 <!-- 心跳折叠提示 -->
 <button
 v-if="hiddenHeartbeatCount > 0"
 class="text-xs text-muted-foreground hover:text-foreground transition-colors mb-2"
 @click="heartbeatExpanded = true"
 >
 还有 {{ hiddenHeartbeatCount }} 条心跳日志...
 </button>
 <!-- 日志行 -->
 <div
 v-for="log in filteredLogs":key="log.id"
 class="flex items-start gap-2 py-0.5 leading-5"
 >
 <span class="text-gray-500 shrink-0">{{ formatTimestamp(log.timestamp) }}</span>
 <span class="shrink-0 w-4 mt-0.5":class="[getLogIcon(log), getLogColor(log)]" />
 <span:class="getLogColor(log)">{{ formatLogMessage(log) }}</span>
 </div>
 </div>
 <!-- 新日志提示按钮 -->
 <Transition
 enter-active-class="transition-all duration-200"
 enter-from-class="opacity-0 translate-y-2"
 enter-to-class="opacity-100 translate-y-0"
 leave-active-class="transition-all duration-150"
 leave-from-class="opacity-100"
 leave-to-class="opacity-0 translate-y-2"
 >
 <button
 v-if="newLogCount > 0 && !isAtBottom"
 class="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-primary/90 text-primary-foreground text-xs backdrop-blur-sm hover:bg-primary transition-colors"
 @click="scrollToBottom"
 >
 已暂停 · 有 {{ newLogCount }} 条新日志
 </button>
 </Transition>
 </div>
 </CardContent>
 </Card>
</template>
