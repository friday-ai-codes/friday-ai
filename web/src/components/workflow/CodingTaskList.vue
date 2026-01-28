<script setup lang="ts">
import { ExternalLink, GitBranch } from 'lucide-vue-next'
import { Badge } from '~/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { ScrollArea } from '~/components/ui/scroll-area'
import type { CodingTask } from '~/types'
interface Props {
 tasks: CodingTask
 loading?: boolean
}
defineProps<Props>
const emit = defineEmits<{
 (e: 'select', task: CodingTask): void
}>
// 状态颜色映射
const statusColors: Record<string, string> = {
 pending: 'bg-gray-100 text-gray-700',
 planning: 'bg-blue-100 text-blue-700',
 plan_review: 'bg-yellow-100 text-yellow-700',
 executing: 'bg-blue-100 text-blue-700',
 code_review: 'bg-yellow-100 text-yellow-700',
 merged: 'bg-green-100 text-green-700',
 failed: 'bg-red-100 text-red-700',
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
</script>
<template>
 <Card class="h-full flex flex-col">
 <CardHeader class="pb-3 border-b">
 <div class="flex items-center gap-2">
 <GitBranch class="w-4 text-primary" />
 <CardTitle class="text-base">编码任务</CardTitle>
 <Badge v-if="tasks.length > 0" variant="secondary" class="text-xs">
 {{ tasks.length }} 个任务
 </Badge>
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
 <p class="text-xs mt-1">AI 编码指派器将在此创建任务</p>
 </div>
 <!-- Task list -->
 <div
 v-for="task in tasks":key="task.id"
 class="group border rounded-lg hover:bg-accent/50 cursor-pointer transition-colors"
 @click="emit('select', task)"
 >
 <div class="flex items-start justify-between gap-2">
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2">
 <span class="font-medium text-sm truncate">{{ task.name }}</span>
 <Badge:class="getStatusColor(task.status)" class="text-[10px] shrink-0">
 {{ getStatusLabel(task.status) }}
 </Badge>
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
