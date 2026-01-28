<script setup lang="ts">
import { Settings, Trash2, X } from 'lucide-vue-next'
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
import { useNodeMeta } from '~/composables/useNodeMeta'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const store = useWorkflowsStore
const nodeTypesStore = useNodeTypesStore
const { currentWorkflow, selectedNode, selectedNodeId } = storeToRefs(store)
// Use node meta composable for registry access
const { getDefinition, hasCustomConfig } = useNodeMeta
// Local form state for workflow settings
const workflowName = ref('')
const workflowDescription = ref('')
const workflowTimeout = ref(3600)
// Local form state for node config
const nodeName = ref('')
const nodeDescription = ref('')
const nodeConfig = ref<Record<string, any>>({})
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
// Watch for workflow changes
watch(currentWorkflow, (workflow) => {
 if (workflow) {
 workflowName.value = workflow.name
 workflowDescription.value = workflow.description
 workflowTimeout.value = workflow.default_timeout
 }
}, { immediate: true })
// Watch for selected node changes
watch(selectedNode, (node) => {
 if (node) {
 nodeName.value = node.data?.name || node.label || ''
 nodeDescription.value = node.data?.description || ''
 nodeConfig.value = { ...node.data?.config }
 }
}, { immediate: true })
function closeNodePanel {
 store.selectNode(null)
}
function deleteNode {
 if (selectedNodeId.value) {
 store.removeNode(selectedNodeId.value)
 }
}
function saveNodeConfig {
 if (!selectedNodeId.value)
 return
 store.updateNodeData(selectedNodeId.value, {
 name: nodeName.value,
 description: nodeDescription.value,
 config: nodeConfig.value,
 })
}
async function saveWorkflowSettings {
 await store.updateWorkflowSettings({
 name: workflowName.value,
 description: workflowDescription.value,
 default_timeout: workflowTimeout.value,
 })
}
// Helper to update config value
function updateConfigValue(key: string, value: any) {
 nodeConfig.value = { ...nodeConfig.value, [key]: value }
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
</script>
<template>
 <div class="h-full w-80 flex flex-col rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <!-- Node Configuration -->
 <template v-if="selectedNode">
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
 <Button variant="ghost" size="icon" class=" w-8 hover:bg-muted/50" @click="closeNodePanel">
 <X class="w-4 " />
 </Button>
 </div>
 </div>
 <ScrollArea class="flex-1">
 <div class=" space-y-5">
 <!-- Basic Info -->
 <div class="space-y-4">
 <div class="space-y-2">
 <Label class="text-sm font-medium">名称</Label>
 <Input v-model="nodeName" placeholder="节点名称" class="bg-background/50" />
 </div>
 <div class="space-y-2">
 <Label class="text-sm font-medium">描述</Label>
 <Textarea v-model="nodeDescription" placeholder="描述此节点的功能..." rows="2" class="bg-background/50" />
 </div>
 </div>
 <Separator class="bg-border/50" />
 <!-- Custom Config Panels (dynamically loaded from registry) -->
 <template v-if="nodeHasCustomConfig && ConfigComponent">
 <component:is="ConfigComponent"
 v-model:config="nodeConfig"
 />
 </template>
 <!-- Dynamic Config Fields (fallback for nodes without custom panels) -->
 <div v-else-if="nodeTypeInfo?.config_schema?.properties" class="space-y-4">
 <h4 class="text-sm font-medium text-muted-foreground flex items-center gap-2">
 <span class="icon-[lucide--sliders-horizontal] text-base" />
 配置项
 </h4>
 <div
 v-for="(propSchema, propKey) in nodeTypeInfo.config_schema.properties":key="propKey"
 class="space-y-2"
 >
 <Label class="flex items-center gap-2 text-sm">
 {{ propSchema.title || propKey }}
 <span v-if="nodeTypeInfo.config_schema.required?.includes(propKey)" class="text-destructive">*</span>
 </Label>
 <!-- Text input -->
 <Input
 v-if="getFieldType(propSchema) === 'text'":model-value="nodeConfig[propKey] || propSchema.default || ''":placeholder="propSchema.description"
 class="bg-background/50"
 @update:model-value="updateConfigValue(propKey, $event)"
 />
 <!-- Number input -->
 <Input
 v-else-if="getFieldType(propSchema) === 'number'"
 type="number":model-value="nodeConfig[propKey] ?? propSchema.default ?? 0":min="propSchema.minimum":max="propSchema.maximum"
 class="bg-background/50"
 @update:model-value="updateConfigValue(propKey, Number($event))"
 />
 <!-- Switch -->
 <div v-else-if="getFieldType(propSchema) === 'switch'" class="flex items-center gap-2">
 <Switch:model-value="nodeConfig[propKey] ?? propSchema.default ?? false"
 @update:model-value="updateConfigValue(propKey, $event)"
 />
 <span class="text-sm text-muted-foreground">{{ propSchema.description }}</span>
 </div>
 <!-- Select -->
 <select
 v-else-if="getFieldType(propSchema) === 'select'"
 class="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-1 text-sm focus:border-primary/50 focus:outline-none transition-colors":value="nodeConfig[propKey] || propSchema.default"
 @change="updateConfigValue(propKey, ($event.target as HTMLSelectElement).value)"
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
 @update:model-value="(val) => updateJsonConfig(propKey, val as string)"
 />
 <p v-if="propSchema.description && getFieldType(propSchema) !== 'switch'" class="text-xs text-muted-foreground">
 {{ propSchema.description }}
 </p>
 </div>
 </div>
 </div>
 </ScrollArea>
 <!-- Actions -->
 <div class=" border-t border-border/50 space-y-2">
 <Button class="w-full group relative overflow-hidden" @click="saveNodeConfig">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--save] mr-2" />
 保存节点
 </Button>
 <Button variant="outline" class="w-full hover:border-destructive/50 hover:text-destructive" @click="deleteNode">
 <Trash2 class="w-4 mr-2" />
 删除节点
 </Button>
 </div>
 </template>
 <!-- Workflow Settings -->
 <template v-else>
 <!-- Header -->
 <div class=" border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-primary/20 to-primary/10">
 <Settings class="w-5 text-primary" />
 </div>
 <div>
 <h3 class="text-base font-semibold">
 工作流设置
 </h3>
 <p class="text-xs text-muted-foreground">
 配置工作流基本信息
 </p>
 </div>
 </div>
 </div>
 <ScrollArea class="flex-1">
 <div class=" space-y-5">
 <div class="space-y-4">
 <div class="space-y-2">
 <Label class="text-sm font-medium">名称</Label>
 <Input v-model="workflowName" placeholder="工作流名称" class="bg-background/50" />
 </div>
 <div class="space-y-2">
 <Label class="text-sm font-medium">描述</Label>
 <Textarea v-model="workflowDescription" placeholder="描述您的工作流..." rows="3" class="bg-background/50" />
 </div>
 <div class="space-y-2">
 <Label class="text-sm font-medium">默认超时时间（秒）</Label>
 <Input v-model.number="workflowTimeout" type="number" placeholder="3600" class="bg-background/50" />
 </div>
 </div>
 <Separator class="bg-border/50" />
 <div class=" rounded-xl bg-muted/30 border border-border/30">
 <div class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--mouse-pointer-click] text-base" />
 点击画布中的节点进行配置
 </div>
 </div>
 </div>
 </ScrollArea>
 <!-- Actions -->
 <div class=" border-t border-border/50">
 <Button class="w-full group relative overflow-hidden" @click="saveWorkflowSettings">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 </template>
 </div>
</template>
