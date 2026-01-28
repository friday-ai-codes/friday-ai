<script setup lang="ts">
import type { FeishuEventTriggerConfig } from '~/types/workflow'
import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useConfigModel } from '~/composables/useConfigModel'
import {
 FEISHU_EVENT_TYPE_OPTIONS,
 feishuEventTriggerConfigSchema,
 WORK_ITEM_TYPE_OPTIONS_WITH_ALL,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: FeishuEventTriggerConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: FeishuEventTriggerConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field, arrayField } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: feishuEventTriggerConfigSchema,
})
// 简单字段
const filterProjectKey = field('filter_project_key', '')
const filterWorkItemType = field('filter_work_item_type', '')
const filterStatus = field('filter_status', '')
// 数组字段 - 事件类型多选
const eventTypes = arrayField('event_types', )
</script>
<template>
 <div class="space-y-4">
 <!-- 事件类型多选 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 事件类型
 <span class="text-destructive">*</span>
 </Label>
 <div class="space-y-2 border rounded-md ">
 <div
 v-for="option in FEISHU_EVENT_TYPE_OPTIONS":key="option.value"
 class="flex items-center gap-2"
 >
 <Checkbox:id="`event-${option.value}`":checked="eventTypes.includes(option.value)"
 @update:checked="(checked: boolean) => eventTypes.toggle(option.value, checked)"
 />
 <label:for="`event-${option.value}`"
 class="text-sm cursor-pointer"
 >
 {{ option.label }}
 </label>
 </div>
 </div>
 <p class="text-xs text-muted-foreground">
 选择要监听的飞书事件类型
 </p>
 </div>
 <!-- 项目 Key 过滤 -->
 <div class="space-y-2">
 <Label>项目 Key 过滤</Label>
 <Input
 v-model="filterProjectKey"
 placeholder="留空表示不过滤"
 />
 <p class="text-xs text-muted-foreground">
 只处理指定项目的事件，留空则处理所有项目
 </p>
 </div>
 <!-- 工作项类型过滤 -->
 <div class="space-y-2">
 <Label>工作项类型</Label>
 <Select v-model="filterWorkItemType">
 <SelectTrigger>
 <SelectValue placeholder="选择工作项类型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in WORK_ITEM_TYPE_OPTIONS_WITH_ALL":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 状态过滤 -->
 <div class="space-y-2">
 <Label>状态过滤</Label>
 <Input
 v-model="filterStatus"
 placeholder="如: in_progress, done"
 />
 <p class="text-xs text-muted-foreground">
 只处理指定状态的事件，多个状态用逗号分隔
 </p>
 </div>
 </div>
</template>
