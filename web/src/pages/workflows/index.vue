<script setup lang="ts">
import { GitBranch, Play, Plus } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { markRaw, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useModal } from 'vue-final-modal'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '~/components/ui/card'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import CreateWorkflowModal from '~/components/workflow/CreateWorkflowModal.vue'
const router = useRouter
const store = useWorkflowsStore
const { workflows, loading } = storeToRefs(store)
onMounted( => {
 store.fetchWorkflows
})
function navigateToEditor(id: string) {
 router.push(`/workflows/${id}`)
}
// 新建工作流弹窗
async function openCreateWorkflow {
 const { open } = useModal({
 component: markRaw(CreateWorkflowModal),
 attrs: {
 onConfirm: => {
 // 创建成功后自动刷新列表（Store Action 已处理），这里无需额外跳转，
 // 或者可以跳转到新创建的工作流详情页。
 // createWorkflow action 返回了新工作流对象，如果能获取到 ID 最好跳转
 store.fetchWorkflows // 刷新列表确保一致性
 },
 },
 })
 await open
}
</script>
<template>
 <div class="container py-6 space-y-6">
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
 <Plus class="w-4 mr-2" />
 新建工作流
 </Button>
 </div>
 <div v-if="loading" class="flex justify-center py-12">
 <div class="animate-spin rounded-full w-8 border-b-2 border-primary" />
 </div>
 <div v-else-if="workflows.length === 0" class="text-center py-12 border rounded-lg bg-muted/10">
 <GitBranch class="w-12 mx-auto text-muted-foreground mb-4" />
 <h3 class="text-lg font-medium">
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
 <Card v-for="workflow in workflows":key="workflow.id" class="hover:border-primary/50 transition-colors cursor-pointer" @click="navigateToEditor(workflow.id)">
 <CardHeader>
 <div class="flex items-center justify-between">
 <Badge variant="outline" class="capitalize">
 {{ workflow.trigger_type }}
 </Badge>
 <div class="flex space-x-2">
 <Button variant="ghost" size="icon" @click.stop>
 <Play class="w-4 " />
 </Button>
 </div>
 </div>
 <CardTitle class="mt-4">
 {{ workflow.name }}
 </CardTitle>
 <CardDescription class="line-clamp-2">
 {{ workflow.description || '暂无描述' }}
 </CardDescription>
 </CardHeader>
 <CardFooter class="text-xs text-muted-foreground">
 更新于 {{ new Date(workflow.updated_at).toLocaleDateString('zh-CN') }}
 </CardFooter>
 </Card>
 </div>
 </div>
</template>
