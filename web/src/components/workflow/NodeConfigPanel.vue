<script setup lang="ts">
import { Settings, Trash2, X } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { ScrollArea } from '~/components/ui/scroll-area'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
const store = useWorkflowsStore
const nodeTypesStore = useNodeTypesStore
const { currentWorkflow, selectedNode, selectedNodeId } = storeToRefs(store)
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
 nodeConfig.value = { ...node.data?.config } || {}
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
 <Card class="h-full w-80 border-l rounded-none flex flex-col bg-background">
 <!-- Node Configuration -->
 <template v-if="selectedNode">
 <CardHeader class="border-b pb-3">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <Settings class="w-4 text-muted-foreground" />
 <CardTitle class="text-lg">
 节点配置
 </CardTitle>
 </div>
 <Button variant="ghost" size="icon" class=" w-8" @click="closeNodePanel">
 <X class="w-4 " />
 </Button>
 </div>
 <Badge v-if="nodeTypeInfo" variant="secondary" class="w-fit mt-2">
 {{ nodeTypeInfo.display_name }}
 </Badge>
 </CardHeader>
 <ScrollArea class="flex-1">
 <CardContent class=" space-y-4">
 <!-- Basic Info -->
 <div class="space-y-4">
 <div class="space-y-2">
 <Label>名称</Label>
 <Input v-model="nodeName" placeholder="节点名称" />
 </div>
 <div class="space-y-2">
 <Label>描述</Label>
 <Textarea v-model="nodeDescription" placeholder="描述此节点的功能..." rows="2" />
 </div>
 </div>
 <Separator />
 <!-- Dynamic Config Fields -->
 <div v-if="nodeTypeInfo?.config_schema?.properties" class="space-y-4">
 <h4 class="text-sm font-medium text-muted-foreground">
 配置项
 </h4>
 <div
 v-for="(propSchema, propKey) in nodeTypeInfo.config_schema.properties":key="propKey"
 class="space-y-2"
 >
 <Label class="flex items-center gap-2">
 {{ propSchema.title || propKey }}
 <span v-if="nodeTypeInfo.config_schema.required?.includes(propKey)" class="text-destructive">*</span>
 </Label>
 <!-- Text input -->
 <Input
 v-if="getFieldType(propSchema) === 'text'":model-value="nodeConfig[propKey] || propSchema.default || ''":placeholder="propSchema.description"
 @update:model-value="updateConfigValue(propKey, $event)"
 />
 <!-- Number input -->
 <Input
 v-else-if="getFieldType(propSchema) === 'number'"
 type="number":model-value="nodeConfig[propKey] ?? propSchema.default ?? 0":min="propSchema.minimum":max="propSchema.maximum"
 @update:model-value="updateConfigValue(propKey, Number($event))"
 />
 <!-- Switch -->
 <div v-else-if="getFieldType(propSchema) === 'switch'" class="flex items-center gap-2">
 <Switch:checked="nodeConfig[propKey] ?? propSchema.default ?? false"
 @update:checked="updateConfigValue(propKey, $event)"
 />
 <span class="text-sm text-muted-foreground">{{ propSchema.description }}</span>
 </div>
 <!-- Select -->
 <select
 v-else-if="getFieldType(propSchema) === 'select'"
 class="w-full rounded-md border border-input bg-background px-3 py-1 text-sm":value="nodeConfig[propKey] || propSchema.default"
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
 class="font-mono text-xs"
 @update:model-value="(val) => updateJsonConfig(propKey, val as string)"
 />
 <p v-if="propSchema.description && getFieldType(propSchema) !== 'switch'" class="text-xs text-muted-foreground">
 {{ propSchema.description }}
 </p>
 </div>
 </div>
 </CardContent>
 </ScrollArea>
 <div class=" border-t space-y-2">
 <Button class="w-full" @click="saveNodeConfig">
 保存节点
 </Button>
 <Button variant="destructive" class="w-full" @click="deleteNode">
 <Trash2 class="w-4 mr-2" />
 删除节点
 </Button>
 </div>
 </template>
 <!-- Workflow Settings -->
 <template v-else>
 <CardHeader class="border-b">
 <div class="flex items-center gap-2">
 <Settings class="w-4 text-muted-foreground" />
 <CardTitle class="text-lg">
 工作流设置
 </CardTitle>
 </div>
 </CardHeader>
 <ScrollArea class="flex-1">
 <CardContent class=" space-y-4">
 <div class="space-y-2">
 <Label>名称</Label>
 <Input v-model="workflowName" placeholder="工作流名称" />
 </div>
 <div class="space-y-2">
 <Label>描述</Label>
 <Textarea v-model="workflowDescription" placeholder="描述您的工作流..." rows="3" />
 </div>
 <div class="space-y-2">
 <Label>默认超时时间（秒）</Label>
 <Input v-model.number="workflowTimeout" type="number" placeholder="3600" />
 </div>
 <Separator />
 <div class="text-sm text-muted-foreground">
 <p>点击画布中的节点进行配置。</p>
 </div>
 </CardContent>
 </ScrollArea>
 <div class=" border-t">
 <Button class="w-full" @click="saveWorkflowSettings">
 保存设置
 </Button>
 </div>
 </template>
 </Card>
</template>
