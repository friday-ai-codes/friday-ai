<script setup lang="ts">
import type { ManualTriggerResponse, TriggerEventType } from '~/types'
import { Play } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import { executeWorkflow } from '~/api/workflow'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Textarea } from '~/components/ui/textarea'
interface Props {
 open: boolean
 workflowId: string
 workflowName?: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:open', value: boolean): void
 (e: 'triggered', response: ManualTriggerResponse): void
}>
const triggering = ref(false)
const error = ref<string | null>(null)
// 表单数据
const eventType = ref<TriggerEventType | ''>('')
const inputDataJson = ref('{\n "work_item_id": "",\n "project_key": ""\n}')
// 事件类型选项
const eventTypeOptions: Array<{ value: TriggerEventType | '', label: string }> = [
 { value: '', label: '无事件类型（手动）' },
 { value: 'WorkitemCreateEvent', label: '工作项创建' },
 { value: 'WorkitemStatusEvent', label: '状态变更' },
 { value: 'WorkitemCommentEvent', label: '评论事件' },
 { value: 'WorkitemUpdateEvent', label: '字段更新' },
 { value: 'WorkFlowNodeStatusEvent', label: '节点流转' },
]
// 重置表单
function resetForm {
 eventType.value = ''
 inputDataJson.value = '{\n "work_item_id": "",\n "project_key": ""\n}'
 error.value = null
}
// 监听 open，重置表单
watch( => props.open, (open) => {
 if (open) {
 resetForm
 }
})
// 解析 JSON
function parseInputData: Record<string, any> | null {
 try {
 return JSON.parse(inputDataJson.value)
 }
 catch {
 return null
 }
}
// 触发执行
async function handleTrigger {
 error.value = null
 const inputData = parseInputData
 if (inputData === null) {
 error.value = '输入数据 JSON 格式错误'
 return
 }
 triggering.value = true
 try {
 const response = await executeWorkflow(props.workflowId, {
 event_type: eventType.value || undefined,
 input_data: inputData,
 })
 emit('triggered', response)
 emit('update:open', false)
 }
 catch (e: any) {
 error.value = e.detail || e.message || '触发失败'
 }
 finally {
 triggering.value = false
 }
}
function handleClose {
 emit('update:open', false)
}
</script>
<template>
 <Dialog:open="open" @update:open="emit('update:open', $event)">
 <DialogContent class="sm:max-w-[500px]">
 <DialogHeader>
 <DialogTitle class="flex items-center gap-2">
 <Play class="w-5 text-primary" />
 手动触发工作流
 </DialogTitle>
 <DialogDescription>
 {{ workflowName ? `手动执行工作流: ${workflowName}`: '手动执行工作流' }}
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4 py-4">
 <!-- 事件类型 -->
 <div class="space-y-2">
 <Label>模拟事件类型</Label>
 <Select v-model="eventType">
 <SelectTrigger>
 <SelectValue placeholder="选择事件类型（可选）" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in eventTypeOptions":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 选择要模拟的事件类型，留空表示纯手动触发
 </p>
 </div>
 <!-- 输入数据 -->
 <div class="space-y-2">
 <Label>输入数据 (JSON)</Label>
 <Textarea
 v-model="inputDataJson"
 class="font-mono text-sm "
 placeholder="{&quot;work_item_id&quot;: &quot;123&quot;, &quot;project_key&quot;: &quot;xxx&quot;}"
 />
 <p class="text-xs text-muted-foreground">
 输入触发工作流所需的数据，将作为 <code class="bg-secondary px-1 rounded">input.*</code> 变量
 </p>
 </div>
 <!-- 错误信息 -->
 <div v-if="error" class=" bg-destructive/10 text-destructive text-sm rounded-md">
 {{ error }}
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="handleClose">
 取消
 </Button>
 <Button:disabled="triggering" @click="handleTrigger">
 <Play class="w-4 mr-1" />
 {{ triggering ? '执行中...': '执行' }}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
