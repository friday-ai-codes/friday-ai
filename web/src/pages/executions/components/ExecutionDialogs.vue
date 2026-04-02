<script setup lang="ts">
import type { ResumePreviewNode } from '~/api/workflow'
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Textarea } from '~/components/ui/textarea'
interface Props {
 /** 审批对话框 */
 approvalDialogOpen: boolean
 approvalComment: string
 approving: boolean
 selectedNodeExecution: NodeExecution | null
 /** 触发对话框 */
 triggerDialogOpen: boolean
 triggerInputData: string
 triggering: boolean
 /** 从此继续对话框 */
 resumeDialogOpen: boolean
 resumeNodeName: string
 resumePreviewLoading: boolean
 resumeSkipNodes: ResumePreviewNode
 resumeRerunNodes: ResumePreviewNode
 resuming: boolean
}
defineProps<Props>
const emit = defineEmits<{
 'update:approvalDialogOpen': [value: boolean]
 'update:approvalComment': [value: string]
 'update:triggerDialogOpen': [value: boolean]
 'update:triggerInputData': [value: string]
 'update:resumeDialogOpen': [value: boolean]
 approve:
 reject:
 trigger:
 resumeFromFailed:
}>
</script>
<template>
 <!-- 审批对话框 -->
 <Dialog:open="approvalDialogOpen" @update:open="emit('update:approvalDialogOpen', $event)">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>审核: {{ selectedNodeExecution?.node_name }}</DialogTitle>
 <DialogDescription>
 请审核此节点的执行结果并选择批准或拒绝。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4">
 <div v-if="selectedNodeExecution?.approval_data?.display_data" class=" rounded-lg bg-muted">
 <pre class="text-xs">{{ JSON.stringify(selectedNodeExecution.approval_data.display_data, null, 2) }}</pre>
 </div>
 <div class="space-y-2">
 <label class="text-sm font-medium">备注（可选）</label>
 <Textarea:model-value="approvalComment" placeholder="添加备注..." @update:model-value="emit('update:approvalComment', String($event))" />
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="emit('update:approvalDialogOpen', false)">
 取消
 </Button>
 <Button variant="destructive":disabled="approving" @click="emit('reject')">
 <span class="icon-[lucide--x-circle] w-4 mr-2" />
 拒绝
 </Button>
 <Button:disabled="approving" @click="emit('approve')">
 <span class="icon-[lucide--check-circle] w-4 mr-2" />
 批准
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 <!-- 触发对话框 -->
 <Dialog:open="triggerDialogOpen" @update:open="emit('update:triggerDialogOpen', $event)">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>触发: {{ selectedNodeExecution?.node_name }}</DialogTitle>
 <DialogDescription>
 输入触发数据以启动工作流执行。
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4">
 <div class="space-y-2">
 <label class="text-sm font-medium">输入数据（JSON 格式）</label>
 <Textarea:model-value="triggerInputData"
 placeholder="{&quot;key&quot;: &quot;value&quot;}"
 class="font-mono min-"
 @update:model-value="emit('update:triggerInputData', String($event))"
 />
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="emit('update:triggerDialogOpen', false)">
 取消
 </Button>
 <Button:disabled="triggering" @click="emit('trigger')">
 <span class="icon-[lucide--zap] w-4 mr-2" />
 触发
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 <!-- 从此继续确认对话框 -->
 <Dialog:open="resumeDialogOpen" @update:open="emit('update:resumeDialogOpen', $event)">
 <DialogContent class="max-w-md">
 <DialogHeader>
 <DialogTitle>从此继续执行</DialogTitle>
 <DialogDescription>
 将从「{{ resumeNodeName }}」节点开始重新执行。
 </DialogDescription>
 </DialogHeader>
 <!-- 影响范围详情 -->
 <div v-if="resumePreviewLoading" class="flex items-center justify-center py-4">
 <span class="icon-[lucide--loader-2] w-5 animate-spin text-muted-foreground" />
 <span class="ml-2 text-sm text-muted-foreground">正在分析影响范围...</span>
 </div>
 <div v-else class="space-y-3">
 <!-- 将被跳过的节点 -->
 <div v-if="resumeSkipNodes.length > 0">
 <p class="text-xs font-medium text-muted-foreground mb-1.5">
 <span class="icon-[lucide--skip-forward] w-3.5 .5 inline-block mr-1 align-text-bottom" />
 跳过（复用结果） · {{ resumeSkipNodes.length }} 个
 </p>
 <div class="flex flex-wrap gap-1">
 <Badge v-for="node in resumeSkipNodes":key="node.id" variant="secondary" class="text-xs">
 {{ node.name }}
 </Badge>
 </div>
 </div>
 <!-- 将重新执行的节点 -->
 <div v-if="resumeRerunNodes.length > 0">
 <p class="text-xs font-medium text-muted-foreground mb-1.5">
 <span class="icon-[lucide--play] w-3.5 .5 inline-block mr-1 align-text-bottom" />
 重新执行 · {{ resumeRerunNodes.length }} 个
 </p>
 <div class="flex flex-wrap gap-1">
 <Badge v-for="node in resumeRerunNodes":key="node.id" variant="outline" class="text-xs border-primary/50">
 {{ node.name }}
 </Badge>
 </div>
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="emit('update:resumeDialogOpen', false)">
 取消
 </Button>
 <Button:disabled="resuming || resumePreviewLoading" @click="emit('resumeFromFailed')">
 <span v-if="resuming" class="icon-[lucide--loader-2] w-4 mr-2 animate-spin" />
 <span v-else class="icon-[lucide--play-circle] w-4 mr-2" />
 确认继续
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
