<script setup lang="ts">
import type { FetchWorkItemConfig } from '~/types/workflow'
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
import { Switch } from '~/components/ui/switch'
import { useConfigModel } from '~/composables/useConfigModel'
import {
 fetchWorkItemConfigSchema,
 WORK_ITEM_FIELD_OPTIONS,
 WORK_ITEM_TYPE_OPTIONS,
} from '~/types/workflow'
// ============================================================================
// Props & Emits
// ============================================================================
interface Props {
 config: FetchWorkItemConfig
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'update:config', value: FetchWorkItemConfig): void
}>
// ============================================================================
// Config Model
// ============================================================================
const { field, arrayField } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: fetchWorkItemConfigSchema,
})
// 简单字段
const workItemId = field('work_item_id', '')
const workItemType = field('work_item_type', 'story')
const setGlobalParams = field('set_global_params', true)
const includeProjectInfo = field('include_project_info', true)
const includeRepositories = field('include_repositories', true)
// 数组字段 - 使用 arrayField 简化 checkbox group
const extractFields = arrayField('extract_fields', ['description', 'prd_url', 'tech_doc_url'])
</script>
<template>
 <div class="space-y-4">
 <!-- 工作项 ID -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2">
 工作项 ID
 <span class="text-destructive">*</span>
 </Label>
 <Input
 v-model="workItemId"
 placeholder="{{input.work_item_id}}"
 class="font-mono"
 />
 <p class="text-xs text-muted-foreground">
 支持模板变量，如 <code class="bg-secondary px-1 rounded">'\{\{ input.work_item_id \}\}'</code>
 </p>
 </div>
 <!-- 工作项类型 -->
 <div class="space-y-2">
 <Label>工作项类型</Label>
 <Select v-model="workItemType">
 <SelectTrigger>
 <SelectValue placeholder="选择工作项类型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in WORK_ITEM_TYPE_OPTIONS":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 提取字段 -->
 <div class="space-y-2">
 <Label>提取字段</Label>
 <div class="space-y-2 border rounded-md ">
 <div
 v-for="option in WORK_ITEM_FIELD_OPTIONS":key="option.value"
 class="flex items-center gap-2"
 >
 <Checkbox:id="`field-${option.value}`":checked="extractFields.includes(option.value)"
 @update:checked="(checked: boolean) => extractFields.toggle(option.value, checked)"
 />
 <label:for="`field-${option.value}`"
 class="text-sm cursor-pointer"
 >
 {{ option.label }}
 </label>
 </div>
 </div>
 </div>
 <!-- 开关选项 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <div>
 <Label>设置为全局参数</Label>
 <p class="text-xs text-muted-foreground">
 提取的字段可被后续节点通过 '\{\{global.xxx\}\}' 访问
 </p>
 </div>
 <Switch v-model="setGlobalParams" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <Label>包含项目信息</Label>
 <p class="text-xs text-muted-foreground">
 输出中包含项目名称、ID 等信息
 </p>
 </div>
 <Switch v-model="includeProjectInfo" />
 </div>
 <div class="flex items-center justify-between">
 <div>
 <Label>包含仓库列表</Label>
 <p class="text-xs text-muted-foreground">
 获取项目关联的代码仓库信息
 </p>
 </div>
 <Switch v-model="includeRepositories" />
 </div>
 </div>
 </div>
</template>
