<script setup lang="ts">
import type { Model } from '~/api/chat'
import type { SettingRead } from '~/api/settings'
import { SettingKey } from '~/api/settings'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
interface Props {
 apiKeyValue: string
 baseUrlValue: string
 defaultModelValue: string
 gitProxyValue: string
 showApiKey: boolean
 models: Model
 loadingModels: boolean
 saving: boolean
 hasUnsavedChanges: boolean
 canTest: boolean
 settingsMeta: Record<string, { label: string, description: string, placeholder: string }>
 getSettingByKey: (key: SettingKey) => SettingRead | undefined
}
const props = defineProps<Props>
const emit = defineEmits<{
 'update:apiKeyValue': [value: string]
 'update:baseUrlValue': [value: string]
 'update:defaultModelValue': [value: string]
 'update:gitProxyValue': [value: string]
 'update:showApiKey': [value: boolean]
 'apiKeyInput':
 'baseUrlInput':
 'defaultModelInput':
 'gitProxyInput':
 'save':
 'remove': [key: SettingKey]
 'openTest':
 'fetchModels':
}>
</script>
<template>
 <section class="group relative">
 <div class="card overflow-hidden">
 <!-- 卡片头部 -->
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-primary/5 to-secondary/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--bot] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 Claude Code 配置
 </h2>
 <p class="text-sm text-muted-foreground">
 Anthropic API 凭证，用于 AI 开发任务
 </p>
 </div>
 </div>
 <!-- 表单内容 -->
 <div class=" space-y-6">
 <!-- API Key 字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="api-key" class="text-base font-medium">
 {{ props.settingsMeta[SettingKey.ANTHROPIC_API_KEY].label }}
 </Label>
 <span
 v-if="props.getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value"
 class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-600 bg-emerald-500/10 rounded-full"
 >
 <span class="icon-[lucide--check-circle]" />
 已配置
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ props.settingsMeta[SettingKey.ANTHROPIC_API_KEY].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="api-key":model-value="props.apiKeyValue":type="props.showApiKey ? 'text': 'password'":placeholder="props.settingsMeta[SettingKey.ANTHROPIC_API_KEY].placeholder"
 class="pl-10 pr-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string | number) => emit('update:apiKeyValue', String(v))"
 @input="emit('apiKeyInput')"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="emit('update:showApiKey', !props.showApiKey)"
 >
 <span:class="props.showApiKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 <button
 v-if="props.getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value"
 class="btn btn-secondary":disabled="props.saving"
 @click="emit('remove', SettingKey.ANTHROPIC_API_KEY)"
 >
 <span class="icon-[lucide--trash-2]" />
 删除
 </button>
 </div>
 </div>
 <!-- Base URL 字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="base-url" class="text-base font-medium">
 {{ props.settingsMeta[SettingKey.ANTHROPIC_BASE_URL].label }}
 </Label>
 <span
 v-if="props.getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.value"
 class="text-xs text-muted-foreground"
 >
 已自定义
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ props.settingsMeta[SettingKey.ANTHROPIC_BASE_URL].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
 <Input
 id="base-url":model-value="props.baseUrlValue"
 type="url":placeholder="props.settingsMeta[SettingKey.ANTHROPIC_BASE_URL].placeholder"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string | number) => emit('update:baseUrlValue', String(v))"
 @input="emit('baseUrlInput')"
 />
 </div>
 <button
 v-if="props.getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.has_value"
 class="btn btn-secondary":disabled="props.saving"
 @click="emit('remove', SettingKey.ANTHROPIC_BASE_URL)"
 >
 <span class="icon-[lucide--trash-2]" />
 删除
 </button>
 </div>
 <p v-if="props.getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.value" class="text-sm text-muted-foreground">
 当前值: {{ props.getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.value }}
 </p>
 </div>
 <!-- 默认模型字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="default-model" class="text-base font-medium">
 {{ props.settingsMeta[SettingKey.ANTHROPIC_MODEL].label }}
 </Label>
 <span
 v-if="props.getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.value"
 class="text-xs text-muted-foreground"
 >
 已自定义
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ props.settingsMeta[SettingKey.ANTHROPIC_MODEL].description }}
 </p>
 <div class="flex gap-2">
 <div class="flex-1">
 <div v-if="props.loadingModels" class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 正在获取模型列表...
 </div>
 <Select
 v-else-if="props.models.length > 0":model-value="props.defaultModelValue"
 @update:model-value="(v: string) => { emit('update:defaultModelValue', v); emit('defaultModelInput') }"
 >
 <SelectTrigger class=" bg-muted/30 border-border/50">
 <SelectValue placeholder="选择默认模型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__default__">
 使用内置默认
 </SelectItem>
 <SelectItem
 v-for="model in props.models":key="model.id":value="model.id"
 >
 {{ model.name || model.id }}
 </SelectItem>
 </SelectContent>
 </Select>
 <div v-else class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--cpu] text-muted-foreground" />
 <Input
 id="default-model":model-value="props.defaultModelValue === '__default__' ? '': props.defaultModelValue":placeholder="props.settingsMeta[SettingKey.ANTHROPIC_MODEL].placeholder"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string | number) => { emit('update:defaultModelValue', String(v) || '__default__'); emit('defaultModelInput') }"
 />
 </div>
 </div>
 <button
 v-if="props.canTest"
 class="btn btn-secondary btn-icon shrink-0":disabled="props.loadingModels"
 title="刷新"
 @click="emit('fetchModels')"
 >
 <span
 class="icon-[lucide--refresh-cw] w-5":class="props.loadingModels && 'animate-spin'"
 />
 </button>
 <button
 v-if="props.getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.has_value"
 class="btn btn-secondary":disabled="props.saving"
 @click="emit('remove', SettingKey.ANTHROPIC_MODEL)"
 >
 <span class="icon-[lucide--trash-2]" />
 删除
 </button>
 </div>
 <p v-if="props.getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.value" class="text-sm text-muted-foreground">
 当前值: {{ props.getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.value }}
 </p>
 </div>
 <!-- Git Proxy 字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="git-proxy" class="text-base font-medium">
 {{ props.settingsMeta[SettingKey.GIT_HTTP_PROXY].label }}
 </Label>
 <span
 v-if="props.getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.value"
 class="text-xs text-muted-foreground"
 >
 已配置
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ props.settingsMeta[SettingKey.GIT_HTTP_PROXY].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--network] text-muted-foreground" />
 <Input
 id="git-proxy":model-value="props.gitProxyValue"
 type="url":placeholder="props.settingsMeta[SettingKey.GIT_HTTP_PROXY].placeholder"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string | number) => emit('update:gitProxyValue', String(v))"
 @input="emit('gitProxyInput')"
 />
 </div>
 <button
 v-if="props.getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.has_value"
 class="btn btn-secondary":disabled="props.saving"
 @click="emit('remove', SettingKey.GIT_HTTP_PROXY)"
 >
 <span class="icon-[lucide--trash-2]" />
 删除
 </button>
 </div>
 <p v-if="props.getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.value" class="text-sm text-muted-foreground">
 当前值: {{ props.getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.value }}
 </p>
 </div>
 </div>
 <!-- 保存按钮区域 -->
 <div class="flex justify-end gap-3 px-6 py-4 border-t border-border/50">
 <button
 v-if="props.canTest"
 class="btn btn-secondary"
 @click="emit('openTest')"
 >
 <span class="icon-[lucide--flask-conical]" />
 连接测试
 </button>
 <button:disabled="props.saving || !props.hasUnsavedChanges"
 class="btn btn-primary"
 @click="emit('save')"
 >
 <span v-if="props.saving" class="icon-[lucide--loader-circle] animate-spin" />
 <span v-else class="icon-[lucide--save]" />
 保存设置
 </button>
 </div>
 </div>
 </section>
</template>
