<script setup lang="ts">
import type { CodingTask } from '~/types'
import { computed } from 'vue'
import { ExternalLink, GitBranch } from 'lucide-vue-next'
import { Badge } from '~/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { ScrollArea } from '~/components/ui/scroll-area'
interface Props {
 tasks: CodingTask
 loading?: boolean
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'select', task: CodingTask): void
}>
// 状态颜色映射 - 使用 glassmorphism 风格
const statusColors: Record<string, string> = {
 pending: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
 planning: 'bg-gradient-to-r from-blue-500/20 to-cyan-500/10 text-blue-700 dark:text-blue-400 animate-pulse',
 plan_review: 'bg-gradient-to-r from-violet-500/20 to-purple-500/10 text-violet-700 dark:text-violet-400',
 executing: 'bg-gradient-to-r from-blue-500/20 to-cyan-500/10 text-blue-700 dark:text-blue-400 animate-pulse',
 code_review: 'bg-gradient-to-r from-violet-500/20 to-purple-500/10 text-violet-700 dark:text-violet-400',
 merged: 'bg-gradient-to-r from-emerald-500/20 to-teal-500/10 text-emerald-700 dark:text-emerald-400',
 failed: 'bg-gradient-to-r from-red-500/20 to-rose-500/10 text-red-700 dark:text-red-400',
}
// 状态中文映射
const statusLabels: Record<string, string> = {
 pending: '待执行',
 planning: '规划中',
 plan_review: '方案评审',
 executing: '执行中',
 code_review: '代码评审',
 merged: '已合并',
 failed: '失败',
}
function getStatusColor(status: string): string {
 return statusColors[status] || statusColors.pending
}
function getStatusLabel(status: string): string {
 return statusLabels[status] || status
}
// 任务统计
const completedCount = computed( =>
 props.tasks.filter(t => t.status === 'merged').length,
)
const failedCount = computed( =>
 props.tasks.filter(t => t.status === 'failed').length,
)
const runningCount = computed( =>
 props.tasks.filter(t => ['planning', 'executing'].includes(t.status)).length,
)
</script>
<template>
 <Card class="h-full flex flex-col">
 <CardHeader class="pb-3 border-b">
 <div class="flex items-center gap-2">
 <GitBranch class="w-4 text-primary" />
 <CardTitle class="text-base">
 编码任务
 </CardTitle>
 <Badge v-if="tasks.length > 0" variant="secondary" class="text-xs">
 {{ tasks.length }} 个任务
 </Badge>
 </div>
 <!-- Task counts summary -->
 <div v-if="tasks.length > 0" class="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
 <span v-if="completedCount" class="text-emerald-500">
 {{ completedCount }} 完成
 </span>
 <span v-if="failedCount" class="text-red-500">
 {{ failedCount }} 失败
 </span>
 <span v-if="runningCount" class="text-blue-500">
 {{ runningCount }} 执行中
 </span>
 </div>
 </CardHeader>
 <ScrollArea class="flex-1">
 <CardContent class=" space-y-2">
 <!-- Loading -->
 <div v-if="loading" class="text-center py-8 text-muted-foreground">
 <div class="animate-spin w-6 border-2 border-primary border-t-transparent rounded-full mx-auto mb-2" />
 加载中...
 </div>
 <!-- Empty state -->
 <div v-else-if="tasks.length === 0" class="text-center py-8 text-muted-foreground">
 <GitBranch class="w-8 mx-auto mb-2 opacity-50" />
 <p>暂无编码任务</p>
 <p class="text-xs mt-1">
 AI 编码指派器将在此创建任务
 </p>
 </div>
 <!-- Task list -->
 <div
 v-for="task in tasks":key="task.id"
 class="group border rounded-xl bg-card/70 backdrop-blur-sm border-border/50
 hover:bg-accent/50 hover:border-primary/30 cursor-pointer transition-all duration-300"
 @click="emit('select', task)"
 >
 <div class="flex items-start justify-between gap-2">
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2 flex-wrap">
 <span class="font-medium text-sm truncate">{{ task.name }}</span>
 <Badge:class="getStatusColor(task.status)" class="text-[10px] shrink-0">
 <span v-if="task.status === 'failed'" class="icon-[lucide--x-circle] w-3 mr-0.5" />
 {{ getStatusLabel(task.status) }}
 </Badge>
 <!-- Merged task indicator -->
 <div
 v-if="task.execution_plan_ids?.length > 1"
 class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
 bg-gradient-to-r from-blue-500/20 to-cyan-500/10
 text-xs text-blue-600 dark:text-blue-400"
 >
 <span class="icon-[lucide--git-merge] text-sm" />
 {{ task.execution_plan_ids.length }} 个任务合并
 </div>
 </div>
 <p v-if="task.description" class="text-xs text-muted-foreground truncate mt-1">
 {{ task.description }}
 </p>
 <div class="flex items-center gap-3 mt-2 text-[10px] text-muted-foreground">
 <span v-if="task.repository_name" class="flex items-center gap-1">
 <GitBranch class="w-3 " />
 {{ task.repository_name }}
 </span>
 <span v-if="task.branch_name">
 分支: {{ task.branch_name }}
 </span>
 </div>
 <!-- Failed task error message -->
 <div
 v-if="task.status === 'failed' && task.error_message"
 class="mt-2 rounded-lg bg-red-50 dark:bg-red-900/20
 border border-red-200 dark:border-red-800"
 >
 <p class="text-sm text-red-600 dark:text-red-400">
 {{ task.error_message }}
 </p>
 </div>
 </div>
 <!-- PR Link -->
 <a
 v-if="task.pr_url":href="task.pr_url"
 target="_blank"
 rel="noopener noreferrer"
 class="shrink-0 .5 hover:bg-accent rounded"
 @click.stop
 >
 <ExternalLink class="w-4 text-primary" />
 </a>
 </div>
 </div>
 </CardContent>
 </ScrollArea>
 </Card>
</template>
