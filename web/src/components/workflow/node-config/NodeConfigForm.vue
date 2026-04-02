<script setup lang="ts">
import type { Component } from 'vue'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
interface Props {
 nodeName: string
 nodeDescription: string
 nodeHasCustomConfig: boolean
 configComponent: Component | null
 nodeConfig: Record<string, any>
 nodeTypeInfo: any
 workflowNodes: any
 workflowEdges: any
 currentNodeId: string | null
}
const props = defineProps<Props>
const emit = defineEmits<{
 'update:name': [value: string]
 'update:description': [value: string]
 'updateConfig': [config: Record<string, any>]
 'updateConfigValue': [key: string, value: any]
 'updateJsonConfig': [key: string, value: string]
}>
// 根据 schema 判断字段类型
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
 <div class="space-y-4">
 <div class="space-y-2">
 <Label class="text-sm font-medium flex items-center justify-between">
 <span>名称</span>
 <span class="text-xs text-muted-foreground">{{ nodeName.length }}/50</span>
 </Label>
 <Input:model-value="nodeName" placeholder="节点名称" maxlength="50" class="bg-background/50" @update:model-value="emit('update:name', $event as string)" />
 </div>
 <div class="space-y-2">
 <Label class="text-sm font-medium flex items-center justify-between">
 <span>描述</span>
 <span class="text-xs text-muted-foreground">{{ nodeDescription.length }}/200</span>
 </Label>
 <Textarea:model-value="nodeDescription" placeholder="描述此节点的功能..." rows="2" maxlength="200" class="bg-background/50" @update:model-value="emit('update:description', $event as string)" />
 </div>
 </div>
 <Separator class="bg-border/50" />
 <!-- 自定义配置面板（从注册表动态加载） -->
 <template v-if="nodeHasCustomConfig && configComponent">
 <component:is="configComponent":config="nodeConfig":workflow-nodes="workflowNodes":workflow-edges="workflowEdges":current-node-id="currentNodeId":node-type-info="nodeTypeInfo"
 @update:config="emit('updateConfig', $event)"
 />
 </template>
 <!-- 动态配置字段（无自定义面板时的后备方案） -->
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
 @update:model-value="emit('updateConfigValue', String(propKey), $event)"
 />
 <!-- Number input -->
 <Input
 v-else-if="getFieldType(propSchema) === 'number'"
 type="number":model-value="nodeConfig[propKey] ?? propSchema.default ?? 0":min="propSchema.minimum":max="propSchema.maximum"
 class="bg-background/50"
 @update:model-value="emit('updateConfigValue', String(propKey), Number($event))"
 />
 <!-- Switch -->
 <div v-else-if="getFieldType(propSchema) === 'switch'" class="flex items-center gap-2">
 <Switch:model-value="nodeConfig[propKey] ?? propSchema.default ?? false"
 @update:model-value="emit('updateConfigValue', String(propKey), $event)"
 />
 <span class="text-sm text-muted-foreground">{{ propSchema.description }}</span>
 </div>
 <!-- Select -->
 <select
 v-else-if="getFieldType(propSchema) === 'select'"
 class="w-full rounded-xl border border-border/50 bg-background/50 px-3 py-1 text-sm focus:border-primary/50 focus:outline-none transition-colors":value="nodeConfig[propKey] || propSchema.default"
 @change="emit('updateConfigValue', String(propKey), ($event.target as HTMLSelectElement).value)"
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
 @update:model-value="emit('updateJsonConfig', String(propKey), $event as string)"
 />
 <p v-if="propSchema.description && getFieldType(propSchema) !== 'switch'" class="text-xs text-muted-foreground">
 {{ propSchema.description }}
 </p>
 </div>
 </div>
</template>
