<script setup lang="ts">
import type { WorkflowTrigger } from '~/types'
import { Edit, Plus, Trash2, Zap } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { deleteTrigger, listTriggers, updateTrigger } from '~/api/workflow'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Switch } from '~/components/ui/switch'
interface Props {
 workflowId: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'add'): void
 (e: 'edit', trigger: WorkflowTrigger): void
}>
const triggers = ref<WorkflowTrigger>
const loading = ref(false)
// 事件类型中文映射
const eventTypeLabels: Record<string, string> = {
 WorkitemCreateEvent: '工作项创建',
 WorkitemStatusEvent: '状态变更',
 WorkitemCommentEvent: '评论事件',
 WorkitemUpdateEvent: '字段更新',
 WorkFlowNodeStatusEvent: '节点流转',
}
function getEventTypeLabel(type: string): string {
 return eventTypeLabels[type] || type
}
// 加载触发器列表
async function loadTriggers {
 if (!props.workflowId)
 return
 loading.value = true
 try {
 triggers.value = await listTriggers(props.workflowId)
 }
 catch (error) {
 console.error('Failed to load triggers:', error)
 }
 finally {
 loading.value = false
 }
}
// 切换启用状态
async function toggleActive(trigger: WorkflowTrigger) {
 try {
 await updateTrigger(props.workflowId, trigger.id, {
 is_active: !trigger.is_active,
 })
 trigger.is_active = !trigger.is_active
 }
 catch (error) {
 console.error('Failed to toggle trigger:', error)
 }
}
// 删除触发器
async function handleDelete(trigger: WorkflowTrigger) {
 // eslint-disable-next-line no-alert
 if (!window.confirm(`确定要删除触发器 "${trigger.name || trigger.event_type}" 吗？`)) {
 return
 }
 try {
 await deleteTrigger(props.workflowId, trigger.id)
 triggers.value = triggers.value.filter(t => t.id !== trigger.id)
 }
 catch (error) {
 console.error('Failed to delete trigger:', error)
 }
}
// 活跃触发器数量
const activeTriggerCount = computed( => {
 return triggers.value.filter(t => t.is_active).length
})
onMounted( => {
 loadTriggers
})
// 暴露刷新方法
defineExpose({ refresh: loadTriggers })
</script>
<template>
 <Card class="h-full flex flex-col">
 <CardHeader class="pb-3 border-b">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <Zap class="w-4 text-primary" />
 <CardTitle class="text-base">
 触发器配置
 </CardTitle>
 <Badge v-if="activeTriggerCount > 0" variant="secondary" class="text-xs">
 {{ activeTriggerCount }} 个启用
 </Badge>
 </div>
 <Button size="sm" class="" @click="emit('add')">
 <Plus class="w-4 mr-1" />
 添加
 </Button>
 </div>
 </CardHeader>
 <CardContent class="flex-1 space-y-2 overflow-auto">
 <!-- Loading -->
 <div v-if="loading" class="text-center py-8 text-muted-foreground">
 <div class="animate-spin w-6 border-2 border-primary border-t-transparent rounded-full mx-auto mb-2" />
 加载中...
 </div>
 <!-- Empty state -->
 <div v-else-if="triggers.length === 0" class="text-center py-8 text-muted-foreground">
 <Zap class="w-8 mx-auto mb-2 opacity-50" />
 <p>暂无触发器</p>
 <p class="text-xs mt-1">
 点击上方按钮添加触发器
 </p>
 </div>
 <!-- Trigger list -->
 <div
 v-for="trigger in triggers":key="trigger.id"
 class="group flex items-center gap-3 border rounded-lg hover:bg-accent/50 transition-colors":class="{ 'opacity-50': !trigger.is_active }"
 >
 <!-- 启用开关 -->
 <Switch:model-value="trigger.is_active"
 @update:model-value="toggleActive(trigger)"
 />
 <!-- 触发器信息 -->
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2">
 <span class="font-medium text-sm truncate">
 {{ trigger.name || getEventTypeLabel(trigger.event_type) }}
 </span>
 <Badge variant="outline" class="text-[10px] shrink-0">
 {{ getEventTypeLabel(trigger.event_type) }}
 </Badge>
 </div>
 <p v-if="trigger.description" class="text-xs text-muted-foreground truncate mt-0.5">
 {{ trigger.description }}
 </p>
 <div v-if="trigger.filter_config && Object.keys(trigger.filter_config).length > 0" class="text-[10px] text-muted-foreground mt-1">
 过滤: {{ Object.keys(trigger.filter_config).join(', ') }}
 </div>
 </div>
 <!-- 操作按钮 -->
 <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
 <Button
 variant="ghost"
 size="icon"
 class=" w-7"
 @click="emit('edit', trigger)"
 >
 <Edit class="w-3.5 .5" />
 </Button>
 <Button
 variant="ghost"
 size="icon"
 class=" w-7 text-destructive hover:text-destructive"
 @click="handleDelete(trigger)"
 >
 <Trash2 class="w-3.5 .5" />
 </Button>
 </div>
 </div>
 </CardContent>
 </Card>
</template>
