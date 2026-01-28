<script setup lang="ts">
import { ChevronDown, ChevronRight, Database, Globe, Layers, Variable, Zap } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { Button } from '~/components/ui/button'
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from '~/components/ui/popover'
import { ScrollArea } from '~/components/ui/scroll-area'
import type { ExecutionContext } from '~/types'
interface Props {
 context?: ExecutionContext | null
 modelValue?: string
}
const props = defineProps<Props>
const emit = defineEmits<{
 (e: 'select', variable: string): void
 (e: 'update:modelValue', value: string): void
}>
const isOpen = ref(false)
// 展开状态
const expandedCategories = ref<Record<string, boolean>>({
 trigger: true,
 global: true,
 input: true,
 nodes: false,
})
function toggleCategory(key: string) {
 expandedCategories.value[key] = !expandedCategories.value[key]
}
// 获取可用变量列表
const availableVariables = computed( => {
 const variables: Array<{
 category: string
 categoryLabel: string
 icon: any
 color: string
 items: Array<{ key: string; path: string; value?: any }>
 }> =
 // Trigger data
 if (props.context?.trigger_data) {
 const items = Object.entries(props.context.trigger_data).map(([key, value]) => ({
 key,
 path: `trigger.${key}`,
 value,
 }))
 if (items.length > 0) {
 variables.push({
 category: 'trigger',
 categoryLabel: '触发器数据',
 icon: Zap,
 color: 'text-blue-500',
 items,
 })
 }
 }
 // Global params
 if (props.context?.global_params) {
 const items = Object.entries(props.context.global_params).map(([key, value]) => ({
 key,
 path: `global.${key}`,
 value,
 }))
 if (items.length > 0) {
 variables.push({
 category: 'global',
 categoryLabel: '全局参数',
 icon: Globe,
 color: 'text-green-500',
 items,
 })
 }
 }
 // Input data
 if (props.context?.input_data) {
 const items = Object.entries(props.context.input_data).map(([key, value]) => ({
 key,
 path: `input.${key}`,
 value,
 }))
 if (items.length > 0) {
 variables.push({
 category: 'input',
 categoryLabel: '输入数据',
 icon: Database,
 color: 'text-orange-500',
 items,
 })
 }
 }
 // Node outputs
 if (props.context?.node_outputs) {
 const items: Array<{ key: string; path: string; value?: any }> =
 Object.entries(props.context.node_outputs).forEach(([nodeId, outputs]) => {
 if (typeof outputs === 'object' && outputs !== null) {
 Object.entries(outputs).forEach(([key, value]) => {
 items.push({
 key: `${nodeId}.${key}`,
 path: `nodes.${nodeId}.${key}`,
 value,
 })
 })
 }
 })
 if (items.length > 0) {
 variables.push({
 category: 'nodes',
 categoryLabel: '节点输出',
 icon: Layers,
 color: 'text-purple-500',
 items,
 })
 }
 }
 return variables
})
// 预设常用变量（当没有上下文时显示）
const presetVariables = computed( => [
 {
 category: 'input',
 categoryLabel: '输入数据',
 icon: Database,
 color: 'text-orange-500',
 items: [
 { key: 'work_item_id', path: 'input.work_item_id' },
 { key: 'project_key', path: 'input.project_key' },
 { key: 'event_type', path: 'input.event_type' },
 ],
 },
 {
 category: 'global',
 categoryLabel: '全局参数',
 icon: Globe,
 color: 'text-green-500',
 items: [
 { key: 'description', path: 'global.description' },
 { key: 'prd_url', path: 'global.prd_url' },
 { key: 'tech_doc_url', path: 'global.tech_doc_url' },
 ],
 },
 {
 category: 'trigger',
 categoryLabel: '触发器数据',
 icon: Zap,
 color: 'text-blue-500',
 items: [
 { key: 'event_type', path: 'trigger.event_type' },
 { key: 'trigger_log_id', path: 'trigger.trigger_log_id' },
 ],
 },
])
const displayVariables = computed( => {
 return availableVariables.value.length > 0 ? availableVariables.value: presetVariables.value
})
function selectVariable(path: string) {
 const variable = `{{${path}}}`
 emit('select', variable)
 // 如果有 v-model，追加到现有值
 if (props.modelValue !== undefined) {
 emit('update:modelValue', props.modelValue + variable)
 }
 isOpen.value = false
}
function getValuePreview(value: any): string {
 if (value === undefined) return ''
 if (value === null) return 'null'
 if (typeof value === 'string') {
 return value.length > 30 ? value.substring(0, 30) + '...': value
 }
 if (typeof value === 'object') {
 return JSON.stringify(value).substring(0, 30) + '...'
 }
 return String(value)
}
</script>
<template>
 <Popover v-model:open="isOpen">
 <PopoverTrigger as-child>
 <Button variant="outline" size="sm" class=" px-2 gap-1">
 <Variable class="w-3.5 .5" />
 <span class="text-xs">变量</span>
 </Button>
 </PopoverTrigger>
 <PopoverContent class="w-80 " align="start">
 <div class=" border-b">
 <h4 class="font-medium text-sm">插入变量</h4>
 <p class="text-xs text-muted-foreground mt-1">
 点击变量名插入到输入框
 </p>
 </div>
 <ScrollArea class="">
 <div class=" space-y-1">
 <div v-for="category in displayVariables":key="category.category">
 <button
 class="flex items-center gap-2 w-full hover:bg-accent rounded-md text-left"
 @click="toggleCategory(category.category)"
 >
 <component:is="expandedCategories[category.category] ? ChevronDown: ChevronRight"
 class="w-4 "
 />
 <component:is="category.icon" class="w-4 ":class="category.color" />
 <span class="text-sm font-medium">{{ category.categoryLabel }}</span>
 </button>
 <div v-if="expandedCategories[category.category]" class="ml-6 space-y-0.5">
 <button
 v-for="item in category.items":key="item.path"
 class="flex items-center justify-between w-full .5 hover:bg-accent rounded text-left group"
 @click="selectVariable(item.path)"
 >
 <code class="text-xs":class="category.color">{{ item.key }}</code>
 <span v-if="item.value !== undefined" class="text-[10px] text-muted-foreground truncate max-w-[120px]">
 {{ getValuePreview(item.value) }}
 </span>
 </button>
 </div>
 </div>
 </div>
 </ScrollArea>
 <div class=" border-t bg-muted/50">
 <p class="text-[10px] text-muted-foreground">
 语法: <code class="bg-background px-1 rounded">{{ '{{path.to.value}}' }}</code>
 </p>
 </div>
 </PopoverContent>
 </Popover>
</template>
