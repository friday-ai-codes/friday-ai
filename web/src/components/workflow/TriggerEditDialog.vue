<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import { createTrigger, updateTrigger } from '~/api/workflow'
import type { WorkflowTrigger, WorkflowTriggerCreate, TriggerEventType } from '~/types'
interface Props {
 open: boolean
 workflowId: string
 trigger?: WorkflowTrigger | null
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:open', value: boolean): void
 (e: 'saved', trigger: WorkflowTrigger): void
}>
const saving = ref(false)
// 表单数据
const formData = ref<WorkflowTriggerCreate>({
 event_type: 'WorkitemStatusEvent',
 filter_config: {},
 input_schema: {},
 is_active: true,
 name: '',
 description: '',
})
// 事件类型选项
const eventTypeOptions: Array<{ value: TriggerEventType; label: string }> = [
 { value: 'WorkitemCreateEvent', label: '工作项创建' },
 { value: 'WorkitemStatusEvent', label: '状态变更' },
 { value: 'WorkitemCommentEvent', label: '评论事件' },
 { value: 'WorkitemUpdateEvent', label: '字段更新' },
 { value: 'WorkFlowNodeStatusEvent', label: '节点流转' },
]
// 过滤条件字段
const filterProjectKey = ref('')
const filterWorkItemType = ref('')
const filterStatus = ref('')
// 是否编辑模式
const isEdit = computed( => !!props.trigger)
// 重置表单
function resetForm {
 formData.value = {
 event_type: 'WorkitemStatusEvent',
 filter_config: {},
 input_schema: {},
 is_active: true,
 name: '',
 description: '',
 }
 filterProjectKey.value = ''
 filterWorkItemType.value = ''
 filterStatus.value = ''
}
// 监听 trigger 变化，填充表单
watch( => props.trigger, (trigger) => {
 if (trigger) {
 formData.value = {
 event_type: trigger.event_type,
 filter_config: { ...trigger.filter_config },
 input_schema: { ...trigger.input_schema },
 is_active: trigger.is_active,
 name: trigger.name,
 description: trigger.description,
 }
 filterProjectKey.value = trigger.filter_config?.project_key || ''
 filterWorkItemType.value = trigger.filter_config?.work_item_type || ''
 filterStatus.value = trigger.filter_config?.status || ''
 } else {
 resetForm
 }
}, { immediate: true })
// 监听 open，重置表单
watch( => props.open, (open) => {
 if (open && !props.trigger) {
 resetForm
 }
})
// 构建过滤配置
function buildFilterConfig: Record<string, any> {
 const config: Record<string, any> = {}
 if (filterProjectKey.value) {
 config.project_key = filterProjectKey.value
 }
 if (filterWorkItemType.value) {
 config.work_item_type = filterWorkItemType.value
 }
 if (filterStatus.value) {
 config.status = filterStatus.value.split(',').map(s => s.trim).filter(Boolean)
 }
 return config
}
// 保存
async function handleSave {
 saving.value = true
 try {
 const data: WorkflowTriggerCreate = {
 ...formData.value,
 filter_config: buildFilterConfig,
 }
 let result: WorkflowTrigger
 if (isEdit.value && props.trigger) {
 result = await updateTrigger(props.workflowId, props.trigger.id, data)
 } else {
 result = await createTrigger(props.workflowId, data)
 }
 emit('saved', result)
 emit('update:open', false)
 } catch (error) {
 console.error('Failed to save trigger:', error)
 } finally {
 saving.value = false
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
 <DialogTitle>{{ isEdit ? '编辑触发器': '添加触发器' }}</DialogTitle>
 <DialogDescription>
 配置工作流的触发条件
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4 py-4">
 <!-- 名称 -->
 <div class="space-y-2">
 <Label>名称</Label>
 <Input
 v-model="formData.name"
 placeholder="触发器名称（可选）"
 />
 </div>
 <!-- 事件类型 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 事件类型
 <span class="text-destructive">*</span>
 </Label>
 <Select v-model="formData.event_type">
 <SelectTrigger>
 <SelectValue placeholder="选择事件类型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in eventTypeOptions":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 过滤条件 -->
 <div class="space-y-3">
 <Label class="text-muted-foreground">过滤条件</Label>
 <div class="space-y-2">
 <Label class="text-sm">项目 Key</Label>
 <Input
 v-model="filterProjectKey"
 placeholder="留空表示不过滤"
 />
 </div>
 <div class="space-y-2">
 <Label class="text-sm">工作项类型</Label>
 <Select v-model="filterWorkItemType">
 <SelectTrigger>
 <SelectValue placeholder="全部类型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="">全部类型</SelectItem>
 <SelectItem value="story">需求 (Story)</SelectItem>
 <SelectItem value="task">任务 (Task)</SelectItem>
 <SelectItem value="bug">缺陷 (Bug)</SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div class="space-y-2">
 <Label class="text-sm">状态过滤</Label>
 <Input
 v-model="filterStatus"
 placeholder="如: in_progress, done（逗号分隔）"
 />
 </div>
 </div>
 <!-- 描述 -->
 <div class="space-y-2">
 <Label>描述</Label>
 <Textarea
 v-model="formData.description"
 placeholder="触发器描述（可选）"
 rows="2"
 />
 </div>
 <!-- 启用状态 -->
 <div class="flex items-center justify-between">
 <Label>启用触发器</Label>
 <Switch v-model:checked="formData.is_active" />
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="handleClose">
 取消
 </Button>
 <Button:disabled="saving" @click="handleSave">
 {{ saving ? '保存中...': '保存' }}
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
