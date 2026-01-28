<script setup lang="ts">
import type { Task } from '~/types'
import { VueFinalModal } from 'vue-final-modal'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Separator } from '~/components/ui/separator'
import { STATUS_COLORS, STATUS_LABELS } from '~/types'
const props = defineProps<{
 taskId: string
}>
const emit = defineEmits<{
 cancel:
 closed:
}>
const tasksStore = useTasksStore
const { error: showError } = useToast
const loading = ref(true)
const task = ref<Task | null>(null)
const logs = ref<string>('')
// 格式化日期
function formatDate(dateStr: string | null) {
 if (!dateStr)
 return '-'
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 获取数据
async function fetchData {
 if (!props.taskId)
 return
 loading.value = true
 try {
 // 并行获取任务详情和日志
 const [taskData, logsData] = await Promise.all([
 tasksStore.fetchTask(props.taskId),
 tasksStore.fetchLogs(props.taskId),
 ])
 // 使用返回的数据而不是 store 的状态，避免副作用
 task.value = taskData
 logs.value = logsData
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取任务详情')
 }
 finally {
 loading.value = false
 }
}
onMounted( => {
 fetchData
})
// 监听 ID 变化
watch( => props.taskId, => {
 fetchData
})
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
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10 text-primary">
 <span class="icon-[lucide--list-checks] text-xl" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 任务详情
 </h3>
 <p class="text-sm text-muted-foreground">
 查看任务详细信息和执行日志
 </p>
 </div>
 </div>
 <button
 type="button"
 class=" rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="handleClose"
 >
 <span class="icon-[lucide--x] text-lg" />
 </button>
 </div>
 <!-- Body -->
 <div class="flex-1 overflow-y-auto ">
 <!-- Loading -->
 <div v-if="loading" class="flex flex-col items-center justify-center py-12 space-y-4">
 <span class="icon-[lucide--loader-circle] w-8 animate-spin text-primary" />
 <p class="text-muted-foreground text-sm">
 正在加载任务详情...
 </p>
 </div>
 <!-- Content -->
 <div v-else-if="task" class="space-y-6">
 <!-- Title & Status -->
 <div class="space-y-4">
 <div class="flex items-start justify-between gap-4">
 <h2 class="text-xl font-bold text-foreground leading-tight">
 {{ task.title }}
 </h2>
 <Badge:class="STATUS_COLORS[task.status]" variant="outline" class="shrink-0 px-3 py-1">
 {{ STATUS_LABELS[task.status] }}
 </Badge>
 </div>
 <!-- Meta Info -->
 <div class="flex flex-wrap gap-4 text-sm text-muted-foreground bg-muted/30 rounded-lg border border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--hash] w-4 " />
 <span class="font-mono">{{ task.id.slice(0, 8) }}</span>
 </div>
 <div class="w-px bg-border" />
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--calendar] w-4 " />
 <span>创建于 {{ formatDate(task.created_at) }}</span>
 </div>
 <div class="w-px bg-border" />
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--clock] w-4 " />
 <span>更新于 {{ formatDate(task.updated_at) }}</span>
 </div>
 </div>
 </div>
 <Separator />
 <!-- Description -->
 <div class="space-y-2">
 <h4 class="text-sm font-medium text-foreground flex items-center gap-2">
 <span class="icon-[lucide--align-left] w-4 " />
 任务描述
 </h4>
 <div class=" rounded-lg bg-muted/30 border border-border/50 text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">
 {{ task.description || '暂无描述' }}
 </div>
 </div>
 <!-- Logs -->
 <div class="space-y-2">
 <h4 class="text-sm font-medium text-foreground flex items-center gap-2">
 <span class="icon-[lucide--terminal-square] w-4 " />
 执行日志
 </h4>
 <div class="rounded-lg border bg-[#1e1e1e] shadow-inner overflow-hidden">
 <div class="flex items-center justify-between px-4 py-2 border-b border-white/10 bg-white/5">
 <div class="flex gap-1.5">
 <div class="w-2.5 .5 rounded-full bg-red-500/50" />
 <div class="w-2.5 .5 rounded-full bg-yellow-500/50" />
 <div class="w-2.5 .5 rounded-full bg-green-500/50" />
 </div>
 <span class="text-xs text-white/40 font-mono">Console Output</span>
 </div>
 <div class=" max-h-[300px] overflow-y-auto font-mono text-xs text-gray-300 leading-relaxed scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
 <pre v-if="logs" class="whitespace-pre-wrap">{{ logs }}</pre>
 <div v-else class="flex flex-col items-center justify-center py-8 text-white/20">
 <span class="icon-[lucide--terminal] w-8 mb-2" />
 <p>暂无日志</p>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- Empty State -->
 <div v-else class="flex flex-col items-center justify-center py-12 space-y-4 text-muted-foreground">
 <span class="icon-[lucide--alert-circle] w-12 opacity-20" />
 <p>未找到任务信息</p>
 </div>
 </div>
 <!-- Footer -->
 <div class="flex justify-end gap-3 px-6 py-4 border-t border-border/50 shrink-0">
 <Button variant="outline" @click="handleClose">
 关闭
 </Button>
 </div>
 </VueFinalModal>
</template>
