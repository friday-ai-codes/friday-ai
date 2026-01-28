<script setup lang="ts">
import { ChevronDown, ChevronRight, Copy, Database, Globe, Layers, Zap } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { ScrollArea } from '~/components/ui/scroll-area'
import type { ExecutionContext } from '~/types'
interface Props {
 context: ExecutionContext | null
 loading?: boolean
}
const props = defineProps<Props>
// 展开状态
const expandedSections = ref<Record<string, boolean>>({
 trigger: true,
 global: true,
 nodes: false,
 input: false,
})
function toggleSection(key: string) {
 expandedSections.value[key] = !expandedSections.value[key]
}
// 复制变量路径
function copyVariablePath(path: string) {
 navigator.clipboard.writeText(`{{${path}}}`)
}
// 格式化 JSON 值
function formatValue(value: any): string {
 if (value === null || value === undefined) return 'null'
 if (typeof value === 'object') {
 return JSON.stringify(value, null, 2)
 }
 return String(value)
}
// 判断值是否为对象
function isObject(value: any): boolean {
 return value !== null && typeof value === 'object' && !Array.isArray(value)
}
// 获取对象的键值对
function getEntries(obj: Record<string, any>): Array<[string, any]> {
 return Object.entries(obj || {})
}
// 节点输出按节点分组
const nodeOutputs = computed( => {
 return getEntries(props.context?.node_outputs || {})
})
// 检查是否有数据
const hasData = computed( => {
 if (!props.context) return false
 return (
 Object.keys(props.context.trigger_data || {}).length > 0 ||
 Object.keys(props.context.global_params || {}).length > 0 ||
 Object.keys(props.context.node_outputs || {}).length > 0
 )
})
</script>
<template>
 <Card class="h-full flex flex-col bg-card/80 backdrop-blur-sm">
 <CardHeader class="pb-3 border-b">
 <div class="flex items-center gap-2">
 <Database class="w-4 text-primary" />
 <CardTitle class="text-base">执行上下文</CardTitle>
 </div>
 <div v-if="context" class="flex items-center gap-2 mt-2">
 <span
 class="text-xs px-2 py-0.5 rounded-full":class="{
 'bg-blue-100 text-blue-700': context.status === 'running',
 'bg-green-100 text-green-700': context.status === 'completed',
 'bg-red-100 text-red-700': context.status === 'failed',
 'bg-gray-100 text-gray-700': !['running', 'completed', 'failed'].includes(context.status),
 }"
 >
 {{ context.status }}
 </span>
 <span class="text-xs text-muted-foreground">
 {{ Math.round(context.progress || 0) }}%
 </span>
 <span v-if="context.is_manual_trigger" class="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">
 手动触发
 </span>
 </div>
 </CardHeader>
 <ScrollArea class="flex-1">
 <CardContent class=" space-y-2">
 <!-- Loading state -->
 <div v-if="loading" class="text-center py-8 text-muted-foreground">
 <div class="animate-spin w-6 border-2 border-primary border-t-transparent rounded-full mx-auto mb-2" />
 加载中...
 </div>
 <!-- Empty state -->
 <div v-else-if="!hasData" class="text-center py-8 text-muted-foreground">
 <Database class="w-8 mx-auto mb-2 opacity-50" />
 <p>暂无上下文数据</p>
 </div>
 <template v-else>
 <!-- Trigger Data -->
 <Collapsible v-if="getEntries(context?.trigger_data || {}).length > 0":open="expandedSections.trigger">
 <CollapsibleTrigger class="flex items-center gap-2 w-full hover:bg-accent rounded-md" @click="toggleSection('trigger')">
 <component:is="expandedSections.trigger ? ChevronDown: ChevronRight" class="w-4 " />
 <Zap class="w-4 text-blue-500" />
 <span class="text-sm font-medium">触发器数据</span>
 <span class="text-xs text-muted-foreground ml-auto">trigger.*</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="ml-6 pl-4 border-l space-y-1 py-2">
 <div
 v-for="[key, value] in getEntries(context?.trigger_data || {})":key="key"
 class="group flex items-start gap-2 text-xs hover:bg-accent/50 rounded "
 >
 <code class="text-blue-600 dark:text-blue-400 shrink-0">{{ key }}</code>
 <span class="text-muted-foreground">:</span>
 <pre v-if="isObject(value)" class="flex-1 text-foreground overflow-x-auto">{{ formatValue(value) }}</pre>
 <span v-else class="flex-1 text-foreground truncate">{{ formatValue(value) }}</span>
 <Button
 variant="ghost"
 size="icon"
 class=" w-5 opacity-0 group-hover:opacity-100"
 @click="copyVariablePath(`trigger.${key}`)"
 >
 <Copy class="w-3 " />
 </Button>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Global Params -->
 <Collapsible v-if="getEntries(context?.global_params || {}).length > 0":open="expandedSections.global">
 <CollapsibleTrigger class="flex items-center gap-2 w-full hover:bg-accent rounded-md" @click="toggleSection('global')">
 <component:is="expandedSections.global ? ChevronDown: ChevronRight" class="w-4 " />
 <Globe class="w-4 text-green-500" />
 <span class="text-sm font-medium">全局参数</span>
 <span class="text-xs text-muted-foreground ml-auto">global.*</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="ml-6 pl-4 border-l space-y-1 py-2">
 <div
 v-for="[key, value] in getEntries(context?.global_params || {})":key="key"
 class="group flex items-start gap-2 text-xs hover:bg-accent/50 rounded "
 >
 <code class="text-green-600 dark:text-green-400 shrink-0">{{ key }}</code>
 <span class="text-muted-foreground">:</span>
 <pre v-if="isObject(value)" class="flex-1 text-foreground overflow-x-auto">{{ formatValue(value) }}</pre>
 <span v-else class="flex-1 text-foreground truncate">{{ formatValue(value) }}</span>
 <Button
 variant="ghost"
 size="icon"
 class=" w-5 opacity-0 group-hover:opacity-100"
 @click="copyVariablePath(`global.${key}`)"
 >
 <Copy class="w-3 " />
 </Button>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Node Outputs -->
 <Collapsible v-if="nodeOutputs.length > 0":open="expandedSections.nodes">
 <CollapsibleTrigger class="flex items-center gap-2 w-full hover:bg-accent rounded-md" @click="toggleSection('nodes')">
 <component:is="expandedSections.nodes ? ChevronDown: ChevronRight" class="w-4 " />
 <Layers class="w-4 text-purple-500" />
 <span class="text-sm font-medium">节点输出</span>
 <span class="text-xs text-muted-foreground ml-auto">nodes.*</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="ml-6 pl-4 border-l space-y-3 py-2">
 <div v-for="[nodeId, outputs] in nodeOutputs":key="nodeId" class="space-y-1">
 <div class="text-xs font-medium text-purple-600 dark:text-purple-400">
 {{ nodeId }}
 </div>
 <div class="ml-2 space-y-1">
 <div
 v-for="[key, value] in getEntries(outputs)":key="key"
 class="group flex items-start gap-2 text-xs hover:bg-accent/50 rounded "
 >
 <code class="text-muted-foreground shrink-0">{{ key }}</code>
 <span class="text-muted-foreground">:</span>
 <pre v-if="isObject(value)" class="flex-1 text-foreground overflow-x-auto text-[10px]">{{ formatValue(value) }}</pre>
 <span v-else class="flex-1 text-foreground truncate">{{ formatValue(value) }}</span>
 <Button
 variant="ghost"
 size="icon"
 class=" w-5 opacity-0 group-hover:opacity-100"
 @click="copyVariablePath(`nodes.${nodeId}.${key}`)"
 >
 <Copy class="w-3 " />
 </Button>
 </div>
 </div>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Input Data -->
 <Collapsible v-if="getEntries(context?.input_data || {}).length > 0":open="expandedSections.input">
 <CollapsibleTrigger class="flex items-center gap-2 w-full hover:bg-accent rounded-md" @click="toggleSection('input')">
 <component:is="expandedSections.input ? ChevronDown: ChevronRight" class="w-4 " />
 <Database class="w-4 text-orange-500" />
 <span class="text-sm font-medium">输入数据</span>
 <span class="text-xs text-muted-foreground ml-auto">input.*</span>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="ml-6 pl-4 border-l space-y-1 py-2">
 <div
 v-for="[key, value] in getEntries(context?.input_data || {})":key="key"
 class="group flex items-start gap-2 text-xs hover:bg-accent/50 rounded "
 >
 <code class="text-orange-600 dark:text-orange-400 shrink-0">{{ key }}</code>
 <span class="text-muted-foreground">:</span>
 <pre v-if="isObject(value)" class="flex-1 text-foreground overflow-x-auto text-[10px]">{{ formatValue(value) }}</pre>
 <span v-else class="flex-1 text-foreground truncate">{{ formatValue(value) }}</span>
 <Button
 variant="ghost"
 size="icon"
 class=" w-5 opacity-0 group-hover:opacity-100"
 @click="copyVariablePath(`input.${key}`)"
 >
 <Copy class="w-3 " />
 </Button>
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </template>
 </CardContent>
 </ScrollArea>
 </Card>
</template>
