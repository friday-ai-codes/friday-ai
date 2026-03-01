<script setup lang="ts">
import type { ManualTriggerResponse, TriggerEventType } from '~/types'
import { Play } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
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
interface TriggerInfo {
 id: string
 name: string
 nodeType: string
 eventType: string
}
interface Props {
 open: boolean
 workflowId: string
 workflowName?: string
 triggers: TriggerInfo
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:open', value: boolean): void
 (e: 'triggered', response: ManualTriggerResponse): void
}>
const triggering = ref(false)
const error = ref<string | null>(null)
const selectedTriggerId = ref<string>('')
const inputDataJson = ref('{\n "work_item_id": "",\n "project_key": ""\n}')
// 获取选中触发器的 event_type（用户不可见，后台自动填入）
const autoEventType = computed( => {
 const trigger = props.triggers.find(t => t.id === selectedTriggerId.value)
 return trigger?.eventType || ''
})
// 重置表单
function resetForm {
 // 自动选择：单触发器或多触发器时预选第一个
 selectedTriggerId.value = props.triggers.length >= 1 ? props.triggers[0].id: ''
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
 event_type: (autoEventType.value || undefined) as TriggerEventType | undefined,
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
 测试工作流
 </DialogTitle>
 <DialogDescription>
 选择触发器并配置输入数据，测试工作流执行效果
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4 py-4">
 <!-- 触发器选择（多触发器） -->
 <div v-if="triggers.length > 1" class="space-y-2">
 <Label>选择触发器</Label>
 <Select v-model="selectedTriggerId">
 <SelectTrigger>
 <SelectValue placeholder="选择一个触发器" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="trigger in triggers":key="trigger.id":value="trigger.id"
 >
 {{ trigger.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 单触发器信息 -->
 <div v-else-if="triggers.length === 1" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/50 border border-border/30">
 <span class="icon-[lucide--zap] w-4 text-amber-500" />
 <span class="text-sm text-muted-foreground">触发器：</span>
 <span class="text-sm font-medium">{{ triggers[0].name }}</span>
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
