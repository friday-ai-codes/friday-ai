<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { Check, Copy, Settings, Trash2, Wand2, X } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { useNodeMeta } from '~/composables/useNodeMeta'
import { areTypesCompatible } from '~/composables/useSchemaValidation'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import IssuesPanel from './validation/IssuesPanel.vue'
import OverrideConfirmDialog from './validation/OverrideConfirmDialog.vue'
const store = useWorkflowsStore
const nodeTypesStore = useNodeTypesStore
const { selectedNodeId, nodes, edges } = storeToRefs(store)
// Esc 键关闭面板
function onEscKey(e: KeyboardEvent) {
 if (e.key === 'Escape' && selectedNodeId.value) {
 store.selectNode(null)
 }
}
onMounted( => document.addEventListener('keydown', onEscKey))
onUnmounted( => document.removeEventListener('keydown', onEscKey))
// Compute selectedNode directly in component to ensure reactivity
const selectedNode = computed( => {
 if (!selectedNodeId.value)
 return null
 return nodes.value.find(n => n.id === selectedNodeId.value) || null
})
// Use node meta composable for registry access
const { getDefinition, hasCustomConfig } = useNodeMeta
// Get upstream variables for the selected node
const { designTimeVariables } = useDesignTimeVariables(nodes, edges, selectedNodeId)
// Local form state for node config
const nodeName = ref('')
const nodeDescription = ref('')
const nodeConfig = ref<Record<string, any>>({})
// Override confirmation state
const overrideDialogOpen = ref(false)
const fieldsToOverride = ref<Array<{
 key: string
 label: string
 currentValue: string
 newValue: string
}>>
const pendingFills = ref<Record<string, string>>({})
// Get node type info for selected node
const nodeTypeInfo = computed( => {
 if (!selectedNode.value)
 return null
 const nodeType = selectedNode.value.nodeType
 return nodeTypesStore.getNodeType(nodeType)
})
// Get the current node type for custom config panel
const currentNodeType = computed( => {
 return selectedNode.value?.nodeType || ''
})
// Check if node has custom config panel (from registry)
const nodeHasCustomConfig = computed( => {
 return hasCustomConfig(currentNodeType.value)
})
// Get node definition from registry
const nodeDefinition = computed( => {
 return getDefinition(currentNodeType.value)
})
// Dynamic config component from registry
const ConfigComponent = computed( => {
 const def = nodeDefinition.value
 if (def?.configComponent) {
 return defineAsyncComponent(def.configComponent)
 }
 return null
})
// Watch for selected node changes - only trigger on node ID change to avoid feedback loop
watch( => selectedNode.value?.id, (newId) => {
 if (newId && selectedNode.value) {
 nodeName.value = selectedNode.value.name || ''
 nodeDescription.value = selectedNode.value.description || ''
 nodeConfig.value = { ...selectedNode.value.config }
 }
}, { immediate: true })
// Auto-sync node config to store with debounce
watchDebounced(
 [nodeName, nodeDescription, nodeConfig],
 => {
 if (!selectedNodeId.value)
 return
 store.updateNodeData(selectedNodeId.value, {
 name: nodeName.value,
 description: nodeDescription.value,
 config: nodeConfig.value,
 })
 },
 { debounce: 300, deep: true },
)
function closeNodePanel {
 store.selectNode(null)
}
function deleteNode {
 if (selectedNodeId.value) {
 store.removeNode(selectedNodeId.value)
 }
}
// Helper to update config value
function updateConfigValue(key: string, value: any) {
 nodeConfig.value = { ...nodeConfig.value, [key]: value }
}
// Handle config update from custom config component
function handleConfigUpdate(newConfig: Record<string, any>) {
 nodeConfig.value = { ...newConfig }
}
// Helper to update JSON config safely
function updateJsonConfig(key: string, value: string) {
 try {
 updateConfigValue(key, JSON.parse(value))
 }
 catch {
 // Ignore JSON parse errors while typing
 }
}
// Render config field based on schema
function getFieldType(schema: any): string {
 if (schema.enum)
 return 'select'
 if (schema.type === 'boolean')
 return 'switch'
 if (schema.type === 'number' || schema.type === 'integer')
 return 'number'
 if (schema.type === 'array')
 return 'array'
 if (schema.type === 'object')
 return 'object'
 return 'text'
}
// Auto-fill logic: match upstream variables to node inputs
// Per CONTEXT.md: name priority, type fallback
function computeAutoFills: { fills: Record<string, string>, overrides: typeof fieldsToOverride.value } {
 const fills: Record<string, string> = {}
 const overrides: typeof fieldsToOverride.value =
 const inputs = nodeTypeInfo.value?.inputs ||
 const vars = designTimeVariables.value
 for (const input of inputs) {
 // Find match by name first (case-insensitive)
 let match = vars.find(v =>
 v.key.toLowerCase === input.name.toLowerCase,
 )
 // Fallback to type match
 if (!match) {
 match = vars.find(v => areTypesCompatible(v.type, input.type))
 }
 if (match) {
 const varPath = `{{${match.path}}}`
 const currentVal = nodeConfig.value[input.name]
 if (currentVal && currentVal !== varPath) {
 // Has existing value - needs confirmation
 overrides.push({
 key: input.name,
 label: input.label || input.name,
 currentValue: String(currentVal),
 newValue: varPath,
 })
 }
 else if (!currentVal) {
 // Empty - fill directly
 fills[input.name] = varPath
 }
 }
 }
 return { fills, overrides }
}
function handleAutoFill {
 const { fills, overrides } = computeAutoFills
 if (Object.keys(fills).length === 0 && overrides.length === 0) {
 // Nothing to fill - silent per CONTEXT.md
 return
 }
 // Apply direct fills immediately (silent per CONTEXT.md)
 for (const [key, value] of Object.entries(fills)) {
 nodeConfig.value[key] = value
 }
 // If there are overrides, show confirmation dialog
 if (overrides.length > 0) {
 fieldsToOverride.value = overrides
 pendingFills.value = Object.fromEntries(
 overrides.map(o => [o.key, o.newValue]),
 )
 overrideDialogOpen.value = true
 }
}
function handleOverrideConfirm(selectedKeys: string) {
 for (const key of selectedKeys) {
 if (pendingFills.value[key]) {
 nodeConfig.value[key] = pendingFills.value[key]
 }
 }
 pendingFills.value = {}
}
// 复制节点 ID
const idCopied = ref(false)
async function copyNodeId {
 if (!selectedNodeId.value)
 return
 try {
 await navigator.clipboard.writeText(selectedNodeId.value)
 idCopied.value = true
 setTimeout( => {
 idCopied.value = false
 }, 2000)
 }
 catch {
 // intentionally ignored
 }
}
// 输入/输出 Schema 折叠状态
const inputSchemaOpen = ref(true)
const outputSchemaOpen = ref(true)
// 输入字段项类型
interface InputFieldItem {
 nodeId: string
 nodeShortId: string
 nodeLabel: string
 fieldName: string
 fieldLabel: string
 type: string
 description?: string
 isNested?: boolean
 parentOutput?: string
}
// 获取直接前置节点的输出字段（用于显示 input 可用变量）
// 如果前置节点有详细 schema，展开为具体字段
const directPredecessorOutputs = computed(: InputFieldItem => {
 if (!selectedNodeId.value)
 return
 // 找到直接连接到当前节点的边
 const incomingEdges = edges.value.filter(e => e.target === selectedNodeId.value)
 if (incomingEdges.length === 0)
 return
 const outputs: InputFieldItem =
 for (const edge of incomingEdges) {
 const sourceNode = nodes.value.find(n => n.id === edge.source)
 if (!sourceNode)
 continue
 const sourceNodeType = nodeTypesStore.getNodeType(sourceNode.nodeType)
 if (!sourceNodeType?.outputs)
 continue
 const nodeLabel = sourceNode.name || sourceNodeType.display_name
 const nodeShortId = sourceNode.shortId || sourceNode.id.slice(0, 8)
 for (const output of sourceNodeType.outputs) {
 // 如果有详细 schema，展开具体字段
 if (output.schema?.properties) {
 for (const [propKey, propSchema] of Object.entries(output.schema.properties)) {
 const schema = propSchema as { type?: string, description?: string }
 outputs.push({
 nodeId: sourceNode.id,
 nodeShortId,
 nodeLabel,
 fieldName: propKey,
 fieldLabel: schema.description || propKey,
 type: schema.type || 'any',
 description: schema.description,
 isNested: true,
 parentOutput: output.name,
 })
 }
 }
 else {
 // 没有详细 schema，使用端口级别信息
 outputs.push({
 nodeId: sourceNode.id,
 nodeShortId,
 nodeLabel,
 fieldName: output.name,
 fieldLabel: output.label,
 type: output.type,
 description: output.description,
 isNested: false,
 })
 }
 }
 }
 return outputs
})
// 检查当前节点是否有前置节点
const hasPredecessor = computed( => directPredecessorOutputs.value.length > 0)
// 获取端口类型的显示颜色
function getPortTypeColor(type: string): string {
 const colors: Record<string, string> = {
 string: 'text-green-500',
 number: 'text-blue-500',
 boolean: 'text-amber-500',
 object: 'text-purple-500',
 array: 'text-cyan-500',
 any: 'text-muted-foreground',
 }
 return colors[type] || 'text-muted-foreground'
}
// 生成输出变量引用路径 (使用 shortId)
function getOutputPath(outputName: string): string {
 return `{{nodes.${selectedNode.value?.shortId || selectedNodeId.value}.${outputName}}}`
}
// 生成输入变量引用路径
function getInputPath(outputName: string): string {
 return `{{input.${outputName}}}`
}
// 计算输出字段总数（包含 schema 详细字段）
function getOutputFieldCount: number {
 if (!nodeTypeInfo.value?.outputs)
 return 0
 let count = 0
 for (const output of nodeTypeInfo.value.outputs) {
 if (output.schema?.properties) {
 count += Object.keys(output.schema.properties).length
 }
 else {
 count += 1
 }
 }
 return count
}
</script>
<template>
 <!-- Only show when a node is selected -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 enter-from-class="opacity-0 translate-x-8"
 enter-to-class="opacity-100 translate-x-0"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="opacity-100 translate-x-0"
 leave-to-class="opacity-0 translate-x-8"
 >
 <div
 v-if="selectedNode"
 class="absolute top-0 right-3 bottom-0 w-[400px] z-20 flex flex-col rounded-2xl bg-card/90 backdrop-blur-md border border-border/50 shadow-xl overflow-hidden"
 >
 <!-- Header -->
 <div class=" border-b border-border/50">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-400/10">
 <Settings class="w-5 text-violet-500" />
 </div>
 <div>
 <h3 class="text-base font-semibold">
 节点配置
 </h3>
 <Badge v-if="nodeTypeInfo" variant="secondary" class="mt-1">
 {{ nodeTypeInfo.display_name }}
 </Badge>
 </div>
 </div>
 <div class="flex items-center gap-1">
 <Button
 v-if="nodeTypeInfo?.inputs?.length"
 variant="ghost"
 size="sm"
 class=" hover:bg-muted/50 text-muted-foreground hover:text-foreground"
 @click="handleAutoFill"
 >
 <Wand2 class="w-4 mr-1.5" />
 自动填充
 </Button>
 <Button variant="ghost" size="icon" class=" w-8 hover:bg-muted/50" @click="closeNodePanel">
 <X class="w-4 " />
 </Button>
 </div>
 </div>
 <!-- 节点 ID 显示 (shortId for user display) -->
 <div class="mt-3 flex items-center gap-2">
 <span class="text-xs text-muted-foreground">ID:</span>
 <code class="text-xs font-mono bg-muted/50 px-1.5 py-0.5 rounded">
 {{ selectedNode?.shortId || selectedNodeId }}
 </code>
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 type="button"
 class="inline-flex items-center justify-center w-5 rounded hover:bg-muted/50 transition-colors"
 @click="copyNodeId"
 >
 <Check v-if="idCopied" class="w-3 text-green-500" />
 <Copy v-else class="w-3 text-muted-foreground" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ idCopied ? '已复制': '复制节点 ID' }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 <ScrollArea class="flex-1">
 <div class=" space-y-5">
 <!-- Issues Panel (shows when warnings exist) -->
 <IssuesPanel />
 <div class="space-y-4">
 <div class="space-y-2">
 <Label class="text-sm font-medium flex items-center justify-between">
 <span>名称</span>
 <span class="text-xs text-muted-foreground">{{ nodeName.length }}/50</span>
 </Label>
 <Input v-model="nodeName" placeholder="节点名称" maxlength="50" class="bg-background/50" />
 </div>
 <div class="space-y-2">
 <Label class="text-sm font-medium flex items-center justify-between">
 <span>描述</span>
 <span class="text-xs text-muted-foreground">{{ nodeDescription.length }}/200</span>
 </Label>
 <Textarea v-model="nodeDescription" placeholder="描述此节点的功能..." rows="2" maxlength="200" class="bg-background/50" />
 </div>
 </div>
 <Separator class="bg-border/50" />
 <!-- Custom Config Panels (dynamically loaded from registry) -->
 <template v-if="nodeHasCustomConfig && ConfigComponent">
 <component:is="ConfigComponent":config="nodeConfig":workflow-nodes="nodes":workflow-edges="edges":current-node-id="selectedNodeId":node-type-info="nodeTypeInfo"
 @update:config="handleConfigUpdate"
 />
 </template>
 <!-- Dynamic Config Fields (fallback for nodes without custom panels) -->
 <div v-else-if="nodeTypeInfo?.config_schema?.properties" class="space-y-4">
 <h4 class="text-sm font-medium text-muted-foreground flex items-center gap-2">
 <span class="icon-[lucide--sliders-horizontal] text-base" />
 配置项
 </h4>
 <div
 v-for="(propSchema, propKey) in (nodeTypeInfo.config_schema.properties as Record<string, any>)":key="propKey"
 class="space-y-2"
 >
 <Label class="flex items-center gap-2 text-sm">
 {{ propSchema.title || propKey }}
 <span v-if="nodeTypeInfo.config_schema.required?.includes(String(propKey))" class="text-destructive">*</span>
 </Label>
 <!-- Text input -->
 <Input
 v-if="getFieldType(propSchema) === 'text'":model-value="nodeConfig[propKey] || propSchema.default || ''":placeholder="propSchema.description"
 class="bg-background/50"
 @update:model-value="updateConfigValue(String(propKey), $event)"
 />
 <!-- Number input -->
 <Input
 v-else-if="getFieldType(propSchema) === 'number'"
 type="number":model-value="nodeConfig[propKey] ?? propSchema.default ?? 0":min="propSchema.minimum":max="propSchema.maximum"
 class="bg-background/50"
 @update:model-value="updateConfigValue(String(propKey), Number($event))"
 />
 <!-- Switch -->
 <div v-else-if="getFieldType(propSchema) === 'switch'" class="flex items-center gap-2">
 <Switch:model-value="nodeConfig[propKey] ?? propSchema.default ?? false"
 @update:model-value="updateConfigValue(String(propKey), $event)"
 />
 <span class="text-sm text-muted-foreground">{{ propSchema.description }}</span>
 </div>
 <!-- Select -->
 <select
 v-else-if="getFieldType(propSchema) === 'select'"
 class="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-1 text-sm focus:border-primary/50 focus:outline-none transition-colors":value="nodeConfig[propKey] || propSchema.default"
 @change="updateConfigValue(String(propKey), ($event.target as HTMLSelectElement).value)"
 >
 <option v-for="opt in propSchema.enum":key="opt":value="opt">
 {{ opt }}
 </option>
 </select>
 <!-- Object/Array - JSON editor -->
 <Textarea
 v-else-if="getFieldType(propSchema) === 'object' || getFieldType(propSchema) === 'array'":model-value="JSON.stringify(nodeConfig[propKey] || propSchema.default || {}, null, 2)"
 rows="4"
 class="font-mono text-xs bg-background/50"
 @update:model-value="(val) => updateJsonConfig(String(propKey), val as string)"
 />
 <p v-if="propSchema.description && getFieldType(propSchema) !== 'switch'" class="text-xs text-muted-foreground">
 {{ propSchema.description }}
 </p>
 </div>
 </div>
 <!-- 输入字段（来自前置节点） -->
 <Collapsible v-if="hasPredecessor" v-model:open="inputSchemaOpen" class="mt-4">
 <Separator class="bg-border/50 mb-4" />
 <CollapsibleTrigger class="flex items-center justify-between w-full group">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--arrow-left-from-line] text-base text-blue-500" />
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
 class="px-3 py-2.5 text-xs":class="{ 'border-t border-border/50': idx > 0 }"
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
 <Collapsible v-if="nodeTypeInfo?.outputs?.length" v-model:open="outputSchemaOpen" class="mt-4">
 <Separator class="bg-border/50 mb-4" />
 <CollapsibleTrigger class="flex items-center justify-between w-full group">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--arrow-right-from-line] text-base text-emerald-500" />
 输出字段
 <Badge variant="outline" class="text-xs">
 {{ getOutputFieldCount }}
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
 class="px-3 py-2 text-xs":class="{ 'border-t border-border/50': idx > 0 || propIdx > 0 }"
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
 class="px-3 py-2.5 text-xs":class="{ 'border-t border-border/50': idx > 0 }"
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
 </div>
 </ScrollArea>
 <!-- Actions -->
 <div class=" border-t border-border/50">
 <Button variant="outline" class="w-full hover:border-destructive/50 hover:text-destructive" @click="deleteNode">
 <Trash2 class="w-4 mr-2" />
 删除节点
 </Button>
 </div>
 </div>
 </Transition>
 <!-- Override Confirmation Dialog -->
 <OverrideConfirmDialog
 v-model:open="overrideDialogOpen":fields="fieldsToOverride"
 @confirm="handleOverrideConfirm"
 />
</template>
