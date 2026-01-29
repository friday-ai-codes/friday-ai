<script setup lang="ts">
import type { FetchWorkItemConfig } from '~/types/workflow'
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
 fetchWorkItemConfigSchema,
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
const { field } = useConfigModel({
 config: => props.config,
 emit: v => emit('update:config', v),
 schema: fetchWorkItemConfigSchema,
})
const workItemId = field('work_item_id', '')
const workItemType = field('work_item_type', '')
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
 支持模板变量，如 <code class="bg-secondary px-1 rounded">{{ '\{\{ input.work_item_id \}\}' }}</code>
 </p>
 </div>
 <!-- 工作项类型 -->
 <div class="space-y-2">
 <Label>工作项类型</Label>
 <Select v-model="workItemType">
 <SelectTrigger>
 <SelectValue placeholder="自动（从触发器获取）" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__auto__">
 自动（从触发器获取）
 </SelectItem>
 <SelectItem
 v-for="option in WORK_ITEM_TYPE_OPTIONS":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <p class="text-xs text-muted-foreground">
 选择「自动」则从上游触发器获取类型
 </p>
 </div>
 <!-- 输出说明 -->
 <div class="rounded-lg bg-muted/50 space-y-2">
 <p class="text-xs font-medium">输出数据结构</p>
 <div class="text-xs text-muted-foreground space-y-1 font-mono">
 <div><span class="text-primary">$.name</span> → 工作项名称</div>
 <div><span class="text-primary">$.description</span> → 描述</div>
 <div><span class="text-primary">$.status</span> → 状态</div>
 <div><span class="text-primary">$.fields[?(@.key=='xxx')].value</span> → 自定义字段</div>
 </div>
 <p class="text-xs text-muted-foreground pt-1">
 <span class="icon-[lucide--info] mr-1" />
 使用「变量提取」节点从输出中提取所需字段
 </p>
 </div>
 </div>
</template>
