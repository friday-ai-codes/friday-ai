<script setup lang="ts">
import type { Component } from 'vue'
import type { UiSchema, UiSchemaGroup, UiVisibleIf } from '~/types/workflow/node-definitions/types'
import { computed, ref } from 'vue'

import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
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
  workflowNodes: any[]
  workflowEdges: any[]
  currentNodeId: string | null
  uiSchema?: UiSchema
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:name': [value: string]
  'update:description': [value: string]
  'updateConfig': [config: Record<string, any>]
  'updateConfigValue': [key: string, value: any]
  'updateJsonConfig': [key: string, value: string]
}>()

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

// ===== uiSchema 渲染逻辑 =====

/** 折叠状态 */
const collapsedGroups = ref<Set<string>>(new Set())

function toggleGroup(groupKey: string) {
  if (collapsedGroups.value.has(groupKey)) {
    collapsedGroups.value.delete(groupKey)
  }
  else {
    collapsedGroups.value.add(groupKey)
  }
}

function isGroupCollapsed(group: UiSchemaGroup): boolean {
  return group.collapsed ? !collapsedGroups.value.has(group.key) : collapsedGroups.value.has(group.key)
}

/** 检查 visible_if 条件 */
function isVisible(visibleIf: UiVisibleIf | undefined): boolean {
  if (!visibleIf)
    return true
  const actual = props.nodeConfig[visibleIf.field]
  switch (visibleIf.operator) {
    case 'eq': return actual === visibleIf.value
    case 'ne': return actual !== visibleIf.value
    case 'in': return Array.isArray(visibleIf.value) && visibleIf.value.includes(actual)
    case 'not_in': return Array.isArray(visibleIf.value) && !visibleIf.value.includes(actual)
    default: return true
  }
}

/** 根据 uiSchema widget 决定字段渲染类型 */
function getUiWidgetType(fieldKey: string): string {
  const field = props.uiSchema?.fields?.[fieldKey]
  if (!field?.widget) {
    // fallback: 从 config_schema 推断
    const propSchema = props.nodeTypeInfo?.config_schema?.properties?.[fieldKey]
    return propSchema ? getFieldType(propSchema) : 'text'
  }
  return field.widget
}

/** 获取字段的 enum 选项（从 config_schema） */
function getFieldEnum(fieldKey: string): string[] | null {
  const propSchema = props.nodeTypeInfo?.config_schema?.properties?.[fieldKey]
  return propSchema?.enum ?? null
}

/** 获取渲染字段列表（有 groups 时按 groups 顺序，否则平铺所有 uiSchema.fields） */
const renderFields = computed(() => {
  if (!props.uiSchema)
    return []
  if (props.uiSchema.groups) {
    return props.uiSchema.groups.flatMap(g => g.fields)
  }
  return Object.keys(props.uiSchema.fields ?? {})
})

/** 是否使用 uiSchema 渲染 */
const useUiSchema = computed(() => {
  return !!props.uiSchema && !props.nodeHasCustomConfig
})
</script>

<template>
  <div class="space-y-4">
    <div class="space-y-2">
      <Label class="text-sm font-medium flex items-center justify-between">
        <span>名称</span>
        <span class="text-xs text-muted-foreground">{{ nodeName.length }}/50</span>
      </Label>
      <Input :model-value="nodeName" placeholder="节点名称" maxlength="50" class="bg-background/50" @update:model-value="emit('update:name', $event as string)" />
    </div>
    <div class="space-y-2">
      <Label class="text-sm font-medium flex items-center justify-between">
        <span>描述</span>
        <span class="text-xs text-muted-foreground">{{ nodeDescription.length }}/200</span>
      </Label>
      <Textarea :model-value="nodeDescription" placeholder="描述此节点的功能..." rows="2" maxlength="200" class="bg-background/50" @update:model-value="emit('update:description', $event as string)" />
    </div>
  </div>

  <Separator class="bg-border/50" />

  <!-- 自定义配置面板（从注册表动态加载）— 最高优先级 -->
  <template v-if="nodeHasCustomConfig && configComponent">
    <component
      :is="configComponent"
      :config="nodeConfig"
      :workflow-nodes="workflowNodes"
      :workflow-edges="workflowEdges"
      :current-node-id="currentNodeId"
      :node-type-info="nodeTypeInfo"
      @update:config="emit('updateConfig', $event)"
    />
  </template>

  <!-- uiSchema 声明式渲染 — 70% 简单节点自动表单 -->
  <template v-else-if="useUiSchema && uiSchema">
    <!-- 有分组 -->
    <template v-if="uiSchema.groups">
      <div v-for="group in uiSchema.groups" :key="group.key" class="space-y-3">
        <h4
          class="text-sm font-medium text-muted-foreground flex items-center gap-2 cursor-pointer select-none"
          @click="toggleGroup(group.key)"
        >
          <span class="icon-[lucide--chevron-down] text-base transition-transform" :class="{ '-rotate-90': isGroupCollapsed(group) }" />
          {{ group.label }}
        </h4>
        <template v-if="!isGroupCollapsed(group)">
          <div
            v-for="fieldKey in group.fields"
            :key="fieldKey"
            class="space-y-2"
          >
            <template v-if="isVisible(uiSchema.fields?.[fieldKey]?.visible_if)">
              <Label class="flex items-center gap-2 text-sm">
                {{ nodeTypeInfo?.config_schema?.properties?.[fieldKey]?.title || fieldKey }}
              </Label>

              <!-- text / textarea -->
              <Textarea
                v-if="getUiWidgetType(fieldKey) === 'textarea'"
                :model-value="nodeConfig[fieldKey] ?? ''"
                :placeholder="uiSchema.fields?.[fieldKey]?.placeholder"
                rows="3"
                class="bg-background/50"
                @update:model-value="emit('updateConfigValue', fieldKey, $event)"
              />
              <Input
                v-else-if="getUiWidgetType(fieldKey) === 'text'"
                :model-value="nodeConfig[fieldKey] ?? ''"
                :placeholder="uiSchema.fields?.[fieldKey]?.placeholder"
                class="bg-background/50"
                @update:model-value="emit('updateConfigValue', fieldKey, $event)"
              />

              <!-- number -->
              <Input
                v-else-if="getUiWidgetType(fieldKey) === 'number'"
                type="number"
                :model-value="nodeConfig[fieldKey] ?? 0"
                class="bg-background/50"
                @update:model-value="emit('updateConfigValue', fieldKey, Number($event))"
              />

              <!-- boolean -->
              <div v-else-if="getUiWidgetType(fieldKey) === 'boolean'" class="flex items-center gap-2">
                <Switch
                  :model-value="nodeConfig[fieldKey] ?? false"
                  @update:model-value="emit('updateConfigValue', fieldKey, $event)"
                />
                <span class="text-sm text-muted-foreground">{{ uiSchema.fields?.[fieldKey]?.help }}</span>
              </div>

              <!-- select -->
              <Select
                v-else-if="getUiWidgetType(fieldKey) === 'select'"
                :model-value="nodeConfig[fieldKey] ?? ''"
                @update:model-value="emit('updateConfigValue', fieldKey, $event)"
              >
                <SelectTrigger class="w-full bg-background/50">
                  <SelectValue placeholder="请选择" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="opt in (getFieldEnum(fieldKey) ?? [])" :key="opt" :value="opt">
                    {{ opt }}
                  </SelectItem>
                </SelectContent>
              </Select>

              <!-- json-editor / fallback -->
              <Textarea
                v-else
                :model-value="typeof nodeConfig[fieldKey] === 'object' ? JSON.stringify(nodeConfig[fieldKey], null, 2) : String(nodeConfig[fieldKey] ?? '')"
                rows="4"
                class="font-mono text-xs bg-background/50"
                @update:model-value="emit('updateJsonConfig', fieldKey, $event as string)"
              />

              <p v-if="uiSchema.fields?.[fieldKey]?.help && getUiWidgetType(fieldKey) !== 'boolean'" class="text-xs text-muted-foreground">
                {{ uiSchema.fields?.[fieldKey]?.help }}
              </p>
            </template>
          </div>
        </template>
      </div>
    </template>

    <!-- 无分组：平铺所有字段 -->
    <template v-else>
      <h4 class="text-sm font-medium text-muted-foreground flex items-center gap-2">
        <span class="icon-[lucide--sliders-horizontal] text-base" />
        配置项
      </h4>
      <div
        v-for="fieldKey in renderFields"
        :key="fieldKey"
        class="space-y-2"
      >
        <template v-if="isVisible(uiSchema.fields?.[fieldKey]?.visible_if)">
          <Label class="flex items-center gap-2 text-sm">
            {{ nodeTypeInfo?.config_schema?.properties?.[fieldKey]?.title || fieldKey }}
          </Label>

          <Textarea
            v-if="getUiWidgetType(fieldKey) === 'textarea'"
            :model-value="nodeConfig[fieldKey] ?? ''"
            :placeholder="uiSchema.fields?.[fieldKey]?.placeholder"
            rows="3"
            class="bg-background/50"
            @update:model-value="emit('updateConfigValue', fieldKey, $event)"
          />
          <Input
            v-else-if="getUiWidgetType(fieldKey) === 'text'"
            :model-value="nodeConfig[fieldKey] ?? ''"
            :placeholder="uiSchema.fields?.[fieldKey]?.placeholder"
            class="bg-background/50"
            @update:model-value="emit('updateConfigValue', fieldKey, $event)"
          />
          <Input
            v-else-if="getUiWidgetType(fieldKey) === 'number'"
            type="number"
            :model-value="nodeConfig[fieldKey] ?? 0"
            class="bg-background/50"
            @update:model-value="emit('updateConfigValue', fieldKey, Number($event))"
          />
          <div v-else-if="getUiWidgetType(fieldKey) === 'boolean'" class="flex items-center gap-2">
            <Switch
              :model-value="nodeConfig[fieldKey] ?? false"
              @update:model-value="emit('updateConfigValue', fieldKey, $event)"
            />
            <span class="text-sm text-muted-foreground">{{ uiSchema.fields?.[fieldKey]?.help }}</span>
          </div>
          <Select
            v-else-if="getUiWidgetType(fieldKey) === 'select'"
            :model-value="nodeConfig[fieldKey] ?? ''"
            @update:model-value="emit('updateConfigValue', fieldKey, $event)"
          >
            <SelectTrigger class="w-full bg-background/50">
              <SelectValue placeholder="请选择" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="opt in (getFieldEnum(fieldKey) ?? [])" :key="opt" :value="opt">
                {{ opt }}
              </SelectItem>
            </SelectContent>
          </Select>
          <Textarea
            v-else
            :model-value="typeof nodeConfig[fieldKey] === 'object' ? JSON.stringify(nodeConfig[fieldKey], null, 2) : String(nodeConfig[fieldKey] ?? '')"
            rows="4"
            class="font-mono text-xs bg-background/50"
            @update:model-value="emit('updateJsonConfig', fieldKey, $event as string)"
          />
          <p v-if="uiSchema.fields?.[fieldKey]?.help && getUiWidgetType(fieldKey) !== 'boolean'" class="text-xs text-muted-foreground">
            {{ uiSchema.fields?.[fieldKey]?.help }}
          </p>
        </template>
      </div>
    </template>
  </template>

  <!-- 动态配置字段（最终 fallback：从 config_schema 推断） -->
  <div v-else-if="nodeTypeInfo?.config_schema?.properties" class="space-y-4">
    <h4 class="text-sm font-medium text-muted-foreground flex items-center gap-2">
      <span class="icon-[lucide--sliders-horizontal] text-base" />
      配置项
    </h4>

    <div
      v-for="(propSchema, propKey) in (nodeTypeInfo.config_schema.properties as Record<string, any>)"
      :key="propKey"
      class="space-y-2"
    >
      <Label class="flex items-center gap-2 text-sm">
        {{ propSchema.title || propKey }}
        <span v-if="nodeTypeInfo.config_schema.required?.includes(String(propKey))" class="text-destructive">*</span>
      </Label>

      <!-- Text input -->
      <Input
        v-if="getFieldType(propSchema) === 'text'"
        :model-value="nodeConfig[propKey] || propSchema.default || ''"
        :placeholder="propSchema.description"
        class="bg-background/50"
        @update:model-value="emit('updateConfigValue', String(propKey), $event)"
      />

      <!-- Number input -->
      <Input
        v-else-if="getFieldType(propSchema) === 'number'"
        type="number"
        :model-value="nodeConfig[propKey] ?? propSchema.default ?? 0"
        :min="propSchema.minimum"
        :max="propSchema.maximum"
        class="bg-background/50"
        @update:model-value="emit('updateConfigValue', String(propKey), Number($event))"
      />

      <!-- Switch -->
      <div v-else-if="getFieldType(propSchema) === 'switch'" class="flex items-center gap-2">
        <Switch
          :model-value="nodeConfig[propKey] ?? propSchema.default ?? false"
          @update:model-value="emit('updateConfigValue', String(propKey), $event)"
        />
        <span class="text-sm text-muted-foreground">{{ propSchema.description }}</span>
      </div>

      <!-- Select -->
      <Select
        v-else-if="getFieldType(propSchema) === 'select'"
        :model-value="nodeConfig[propKey] || propSchema.default"
        @update:model-value="emit('updateConfigValue', String(propKey), $event)"
      >
        <SelectTrigger class="w-full bg-background/50">
          <SelectValue placeholder="请选择" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in propSchema.enum" :key="opt" :value="opt">
            {{ opt }}
          </SelectItem>
        </SelectContent>
      </Select>

      <!-- Object/Array - JSON editor -->
      <Textarea
        v-else-if="getFieldType(propSchema) === 'object' || getFieldType(propSchema) === 'array'"
        :model-value="JSON.stringify(nodeConfig[propKey] || propSchema.default || {}, null, 2)"
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
