<script setup lang="ts">
import type { CodingTask } from '~/types'
import { ExternalLink, GitBranch } from 'lucide-vue-next'
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { ScrollArea } from '~/components/ui/scroll-area'
import StatusBadge from '~/components/common/StatusBadge.vue'
interface Props {
 tasks: CodingTask
 loading?: boolean
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'select', task: CodingTask): void
}>
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
 <StatusBadge type="codingTask":status="task.status" size="sm" />
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
 <!-- Partial success info -->
 <div
 v-if="task.status === 'partial_success'"
 class="mt-2 rounded-lg bg-amber-50 dark:bg-amber-900/20
 border border-amber-200 dark:border-amber-800"
 >
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--alert-triangle] w-4 text-amber-500 shrink-0 mt-0.5" />
 <div class="flex-1 min-w-0">
 <p class="text-sm font-medium text-amber-700 dark:text-amber-400">
 代码已推送，但 MR 创建失败
 </p>
 <p v-if="task.branch_name" class="text-xs text-amber-600 dark:text-amber-500 mt-1">
 分支: <code class="px-1 py-0.5 bg-amber-100 dark:bg-amber-900/40 rounded">{{ task.branch_name }}</code>
 </p>
 <p v-if="task.error_message" class="text-xs text-amber-600 dark:text-amber-500 mt-1">
 {{ task.error_message }}
 </p>
 <p class="text-xs text-muted-foreground mt-2">
 请手动创建 MR 或检查仓库配置
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- MR Status Section -->
 <div class="flex items-center gap-2 shrink-0">
 <!-- MR Link with status -->
 <a
 v-if="task.pr_url":href="task.pr_url"
 target="_blank"
 rel="noopener noreferrer"
 class="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg
 bg-gradient-to-r from-emerald-500/20 to-teal-500/10
 text-emerald-700 dark:text-emerald-400
 hover:from-emerald-500/30 hover:to-teal-500/20
 transition-all duration-300"
 @click.stop
 >
 <span class="icon-[lucide--git-pull-request] w-4 " />
 <span class="text-xs font-medium">MR</span>
 <ExternalLink class="w-3 " />
 </a>
 <!-- Conflict warning badge -->
 <div
 v-if="task.pr_url && task.mr_has_conflicts"
 class="inline-flex items-center gap-1 px-2 py-1 rounded-lg
 bg-gradient-to-r from-amber-500/20 to-orange-500/10
 text-amber-600 dark:text-amber-400"
 title="MR 有合并冲突，需要人工解决"
 >
 <span class="icon-[lucide--alert-triangle] w-3 " />
 <span class="text-[10px]">冲突</span>
 </div>
 </div>
 </div>
 </div>
 </CardContent>
 </ScrollArea>
 </Card>
</template>
