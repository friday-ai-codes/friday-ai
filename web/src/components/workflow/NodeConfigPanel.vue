<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { Settings, Trash2, Wand2, X } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import { useDesignTimeVariables } from '~/composables/useDesignTimeVariables'
import { useNodeMeta } from '~/composables/useNodeMeta'
import { areTypesCompatible } from '~/composables/useSchemaValidation'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import IssuesPanel from './validation/IssuesPanel.vue'
import OverrideConfirmDialog from './validation/OverrideConfirmDialog.vue'
const store = useWorkflowsStore
const nodeTypesStore = useNodeTypesStore
const { selectedNode, selectedNodeId, nodes, edges } = storeToRefs(store)
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
 const nodeType = selectedNode.value.data?.node_type || selectedNode.value.type
 return nodeTypesStore.getNodeType(nodeType)
})
// Get the current node type for custom config panel
const currentNodeType = computed( => {
 return selectedNode.value?.data?.node_type || selectedNode.value?.type || ''
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
 nodeName.value = selectedNode.value.data?.name || selectedNode.value.label || ''
 nodeDescription.value = selectedNode.value.data?.description || ''
 nodeConfig.value = { ...selectedNode.value.data?.config }
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
function computeAutoFills: { fills: Record<string, string>; overrides: typeof fieldsToOverride.value } {
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
</script>
<template>
 <!-- Only show when a node is selected -->
 <div
 v-if="selectedNode"
 class="h-full w-80 flex flex-col rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden"
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
 <!-- Override Confirmation Dialog -->
 <OverrideConfirmDialog
 v-model:open="overrideDialogOpen":fields="fieldsToOverride"
 @confirm="handleOverrideConfirm"
 />
</template>
