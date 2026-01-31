<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { markRaw, onMounted } from 'vue'
import { useModal } from 'vue-final-modal'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import ExecutionStatusBadge from '~/components/execution/ExecutionStatusBadge.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '~/components/ui/card'
import CreateWorkflowModal from '~/components/workflow/CreateWorkflowModal.vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const router = useRouter
const store = useWorkflowsStore
const { workflows, loading } = storeToRefs(store)
onMounted( => {
 store.fetchWorkflows
})
function navigateToEditor(id: string) {
 router.push(`/workflows/${id}`)
}
async function executeWorkflow(workflowId: string) {
 try {
 await store.fetchWorkflow(workflowId)
 const result = await store.executeWorkflow({})
 if (result?.execution_id) {
 toast.success('工作流已启动')
 router.push(`/executions/${result.execution_id}`)
 }
 }
 catch (e: any) {
 toast.error(`执行失败: ${e.message}`)
 }
}
function formatRelativeTime(dateStr: string) {
 const date = new Date(dateStr)
 const now = new Date
 const diffMs = now.getTime - date.getTime
 const diffMins = Math.floor(diffMs / 60000)
 const diffHours = Math.floor(diffMs / 3600000)
 const diffDays = Math.floor(diffMs / 86400000)
 if (diffMins < 1)
 return '刚刚'
 if (diffMins < 60)
 return `${diffMins} 分钟前`
 if (diffHours < 24)
 return `${diffHours} 小时前`
 if (diffDays < 7)
 return `${diffDays} 天前`
 return date.toLocaleDateString('zh-CN')
}
// 新建工作流弹窗
async function openCreateWorkflow {
 const { open } = useModal({
 component: markRaw(CreateWorkflowModal),
 attrs: {
 onConfirm: => {
 store.fetchWorkflows
 },
 },
 })
 await open
}
</script>
<template>
 <div class="relative space-y-6 max-w-[1400px] mx-auto pb-10">
 <!-- Background decorations -->
 <div class="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <h1 class="text-3xl font-bold tracking-tight">
 工作流
 </h1>
 <p class="text-muted-foreground mt-2">
 管理和自动化您的开发流程
 </p>
 </div>
 <Button @click="openCreateWorkflow">
 <span class="icon-[lucide--plus] w-4 mr-2" />
 新建工作流
 </Button>
 </div>
 <div v-if="loading" class="flex justify-center py-12">
 <div class="animate-spin rounded-full w-8 border-b-2 border-primary" />
 </div>
 <div v-else-if="workflows.length === 0" class="text-center py-16">
 <div class="inline-flex rounded-2xl bg-gradient-to-br from-muted/50 to-muted/30 mb-4 leading-none">
 <span class="icon-[lucide--git-branch] text-4xl text-muted-foreground" />
 </div>
 <h3 class="text-lg font-medium mb-2">
 暂无工作流
 </h3>
 <p class="text-muted-foreground mb-4">
 创建您的第一个工作流，开始自动化开发流程
 </p>
 <Button @click="openCreateWorkflow">
 创建工作流
 </Button>
 </div>
 <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
 <Card
 v-for="workflow in workflows":key="workflow.id"
 class="group relative rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all duration-300 cursor-pointer"
 @click="navigateToEditor(workflow.id)"
 >
 <!-- Status indicator bar -->
 <div
 v-if="workflow.last_execution"
 class=" w-full":class="{
 'bg-gradient-to-r from-emerald-500 to-emerald-400': workflow.last_execution.status === 'completed',
 'bg-gradient-to-r from-red-500 to-red-400': workflow.last_execution.status === 'failed',
 'bg-gradient-to-r from-blue-500 to-blue-400': workflow.last_execution.status === 'running',
 'bg-gradient-to-r from-yellow-500 to-yellow-400': workflow.last_execution.status === 'paused',
 'bg-gradient-to-r from-gray-400 to-gray-300': !['completed', 'failed', 'running', 'paused'].includes(workflow.last_execution.status),
 }"
 />
 <CardHeader>
 <div class="flex items-center justify-between">
 <Badge variant="outline" class="capitalize">
 {{ workflow.trigger_type }}
 </Badge>
 <div class="flex items-center gap-2">
 <span class="text-xs text-muted-foreground">
 {{ workflow.execution_count || 0 }} 次执行
 </span>
 <Button
 variant="ghost"
 size="icon"
 class=" w-8 opacity-0 group-hover:opacity-100 transition-opacity"
 @click.stop="executeWorkflow(workflow.id)"
 >
 <span class="icon-[lucide--play] w-4 " />
 </Button>
 </div>
 </div>
 <CardTitle class="mt-4 group-hover:text-primary transition-colors">
 {{ workflow.name }}
 </CardTitle>
 <CardDescription class="line-clamp-2">
 {{ workflow.description || '暂无描述' }}
 </CardDescription>
 </CardHeader>
 <CardFooter class="border-t border-border/50 bg-muted/20 flex items-center justify-between">
 <div class="flex items-center gap-2 text-xs text-muted-foreground">
 <ExecutionStatusBadge
 v-if="workflow.last_execution":status="workflow.last_execution.status"
 size="sm"
 />
 <span v-if="workflow.last_execution">
 {{ formatRelativeTime(workflow.last_execution.created_at) }}
 </span>
 <span v-else>
 暂无执行记录
 </span>
 </div>
 <RouterLink:to="`/executions?workflow_id=${workflow.id}`"
 class="text-xs text-muted-foreground hover:text-primary transition-colors flex items-center gap-1"
 @click.stop
 >
 执行历史
 <span class="icon-[lucide--chevron-right] w-3 group-hover:translate-x-0.5 transition-transform" />
 </RouterLink>
 </CardFooter>
 </Card>
 </div>
 </div>
</template>
