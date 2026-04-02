<script setup lang="ts">
import type { InputFieldItem } from './composables/useNodeSchema'
import { Badge } from '~/components/ui/badge'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { Separator } from '~/components/ui/separator'
interface Props {
 directPredecessorOutputs: InputFieldItem
 hasPredecessor: boolean
 nodeTypeInfo: any
 inputSchemaOpen: boolean
 outputSchemaOpen: boolean
 outputFieldCount: number
 getOutputPath: (name: string) => string
 getInputPath: (name: string) => string
}
const props = defineProps<Props>
const emit = defineEmits<{
 'update:inputSchemaOpen': [value: boolean]
 'update:outputSchemaOpen': [value: boolean]
}>
// 纯函数直接 import，不通过 store
function getPortTypeColor(type: string): string {
 const colors: Record<string, string> = {
 string: 'text-green-500',
 number: 'text-primary',
 boolean: 'text-amber-500',
 object: 'text-purple-500',
 array: 'text-cyan-500',
 any: 'text-muted-foreground',
 }
 return colors[type] || 'text-muted-foreground'
}
</script>
<template>
 <!-- 输入字段（来自前置节点） -->
 <Collapsible v-if="hasPredecessor":open="inputSchemaOpen" class="mt-4" @update:open="emit('update:inputSchemaOpen', $event)">
 <Separator class="bg-border/50 mb-4" />
 <CollapsibleTrigger class="flex items-center justify-between w-full group">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--arrow-left-from-line] text-base text-primary" />
 输入字段
 <Badge variant="outline" class="text-xs">
 {{ directPredecessorOutputs.length }}
 </Badge>
 </div>
 <span
 class="icon-[lucide--chevron-down] text-muted-foreground transition-transform duration-200":class="{ 'rotate-180': inputSchemaOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-3">
 <div class="rounded-xl bg-muted/30 border border-border/50 overflow-hidden">
 <div
 v-for="(input, idx) in directPredecessorOutputs":key="`${input.nodeId}-${input.fieldName}`"
 class="px-3 py-2.5 text-xs":class="{ 'border-t border-border/50': Number(idx) > 0 }"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <code class="font-mono font-medium">{{ input.fieldName }}</code>
 <span
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted":class="getPortTypeColor(input.type)"
 >
 {{ input.type }}
 </span>
 </div>
 <span class="text-[10px] text-muted-foreground">
 来自 {{ input.nodeLabel }}
 </span>
 </div>
 <div v-if="input.description" class="mt-1 text-muted-foreground">
 {{ input.description }}
 </div>
 <!-- 引用提示 -->
 <div class="mt-1.5 flex items-center gap-1 text-[10px] text-muted-foreground/70">
 <span class="icon-[lucide--code] text-xs" />
 <code class="font-mono">{{ getInputPath(input.fieldName) }}</code>
 </div>
 </div>
 </div>
 <p class="mt-2 text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--info]" />
 可通过 <code class="px-1 py-0.5 rounded bg-muted font-mono text-[10px]">input.字段名</code> 引用前置节点输出
 </p>
 </CollapsibleContent>
 </Collapsible>
 <!-- 输出 Schema -->
 <Collapsible v-if="nodeTypeInfo?.outputs?.length":open="outputSchemaOpen" class="mt-4" @update:open="emit('update:outputSchemaOpen', $event)">
 <Separator class="bg-border/50 mb-4" />
 <CollapsibleTrigger class="flex items-center justify-between w-full group">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--arrow-right-from-line] text-base text-emerald-500" />
 输出字段
 <Badge variant="outline" class="text-xs">
 {{ outputFieldCount }}
 </Badge>
 </div>
 <span
 class="icon-[lucide--chevron-down] text-muted-foreground transition-transform duration-200":class="{ 'rotate-180': outputSchemaOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="mt-3">
 <div class="rounded-xl bg-muted/30 border border-border/50 overflow-hidden">
 <template v-for="(output, idx) in nodeTypeInfo.outputs":key="output.name">
 <!-- 如果有详细 schema，展示具体字段 -->
 <template v-if="output.schema?.properties">
 <div
 v-for="(propSchema, propKey, propIdx) in output.schema.properties":key="`${output.name}-${propKey}`"
 class="px-3 py-2 text-xs":class="{ 'border-t border-border/50': Number(idx) > 0 || Number(propIdx) > 0 }"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <code class="font-mono font-medium">{{ propKey }}</code>
 <span
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted":class="getPortTypeColor(propSchema.type)"
 >
 {{ propSchema.type }}
 </span>
 </div>
 </div>
 <div v-if="propSchema.description" class="mt-1 text-muted-foreground">
 {{ propSchema.description }}
 </div>
 <!-- 引用提示 -->
 <div class="mt-1.5 flex items-center gap-1 text-[10px] text-muted-foreground/70">
 <span class="icon-[lucide--code] text-xs" />
 <code class="font-mono">{{ getOutputPath(String(propKey)) }}</code>
 </div>
 </div>
 </template>
 <!-- 没有详细 schema，显示端口级别信息 -->
 <template v-else>
 <div
 class="px-3 py-2.5 text-xs":class="{ 'border-t border-border/50': Number(idx) > 0 }"
 >
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <code class="font-mono font-medium">{{ output.name }}</code>
 <span
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-muted":class="getPortTypeColor(output.type)"
 >
 {{ output.type }}
 </span>
 </div>
 </div>
 <div v-if="output.description" class="mt-1 text-muted-foreground">
 {{ output.description }}
 </div>
 <!-- 引用提示 -->
 <div class="mt-1.5 flex items-center gap-1 text-[10px] text-muted-foreground/70">
 <span class="icon-[lucide--code] text-xs" />
 <code class="font-mono">{{ getOutputPath(output.name) }}</code>
 </div>
 </div>
 </template>
 </template>
 </div>
 <p class="mt-2 text-xs text-muted-foreground flex items-center gap-1">
 <span class="icon-[lucide--info]" />
 下游节点可通过上述路径引用输出
 </p>
 </CollapsibleContent>
 </Collapsible>
</template>
