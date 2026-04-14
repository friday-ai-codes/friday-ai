<script setup lang="ts">
/**
 * RunningExecutionsBadge - 工作流编辑器工具栏"运行中"实例徽章
 *
 * 当有运行中/待执行的工作流实例时显示，点击展开 Popover 列出实例列表。
 * Popover 打开时每 5s 轮询刷新数据。
 */
import { useIntervalFn } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '~/api/client'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from '~/components/ui/popover'
interface RunningExecution {
 id: string
 status: string
 trigger_type: string
 created_at: string
}
const props = defineProps<{
 workflowId: string
}>
const router = useRouter
const popoverOpen = ref(false)
const executions = ref<RunningExecution>
const loading = ref(false)
const runningStatuses = ['running', 'pending', 'queued']
const runningExecutions = computed( =>
 executions.value.filter(e => runningStatuses.includes(e.status)),
)
const runningCount = computed( => runningExecutions.value.length)
async function fetchRunningExecutions {
 try {
 loading.value = true
 const data = await get<any>(`/workflow-executions/`, {
 workflow_id: props.workflowId,
 ordering: '-created_at',
 })
 const results = data.results || data
 // 仅保留运行中/待执行的
 executions.value = Array.isArray(results) ? results:
 }
 catch {
 // 静默失败
 }
 finally {
 loading.value = false
 }
}
// Popover 打开时开始轮询，关闭时停止
const { pause, resume } = useIntervalFn(fetchRunningExecutions, 5000, { immediate: false })
watch(popoverOpen, (open) => {
 if (open) {
 fetchRunningExecutions
 resume
 }
 else {
 pause
 }
})
// 初次加载一次获取数量
fetchRunningExecutions
function formatTime(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN', {
 month: 'short',
 day: 'numeric',
 hour: '2-digit',
 minute: '2-digit',
 })
}
function navigateToExecution(executionId: string) {
 popoverOpen.value = false
 router.push(`/executions/${executionId}`)
}
</script>
<template>
 <Popover v-model:open="popoverOpen">
 <PopoverTrigger as-child>
 <Button
 v-if="runningCount > 0"
 variant="ghost"
 size="sm"
 class=" relative"
 >
 <span class="icon-[lucide--activity] w-4 mr-1 text-emerald-500" />
 <span class="text-xs">运行中</span>
 <Badge
 class="absolute -top-1 -right-1 min-w-4 px-1 text-[10px] bg-emerald-500 text-white border-0 animate-pulse"
 >
 {{ runningCount }}
 </Badge>
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" class="w-72 rounded-xl bg-card/95 backdrop-blur-md border border-border/50">
 <div class="px-3 py-2 border-b border-border/50">
 <h4 class="text-sm font-medium">
 运行中的执行
 </h4>
 </div>
 <div class="max- overflow-y-auto">
 <div
 v-for="exec in runningExecutions":key="exec.id"
 class="flex items-center justify-between px-3 py-2 hover:bg-muted/30 transition-colors cursor-pointer group"
 @click="navigateToExecution(exec.id)"
 >
 <div class="flex items-center gap-2 min-w-0">
 <span
 class="w-2 rounded-full shrink-0":class="{ 'bg-primary animate-pulse': exec.status === 'running', 'bg-amber-500': exec.status === 'pending' || exec.status === 'queued' }"
 />
 <span class="text-xs text-muted-foreground truncate">
 {{ formatTime(exec.created_at) }}
 </span>
 </div>
 <span class="icon-[lucide--chevron-right] w-3.5 .5 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
 </div>
 <div v-if="runningExecutions.length === 0 && !loading" class="px-3 py-4 text-center text-xs text-muted-foreground">
 暂无运行中的执行
 </div>
 </div>
 </PopoverContent>
 </Popover>
</template>
