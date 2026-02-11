<script setup lang="ts">
import type { Model } from '~/api/chat'
import type { SettingRead } from '~/api/settings'
import { onMounted, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { getModels } from '~/api/chat'
import {
 deleteSetting,
 getAllSettings,
 SettingKey,
 testFeishuIM,
 updateSetting,
} from '~/api/settings'
import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import VectorIndexSettings from '~/components/settings/VectorIndexSettings.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Textarea } from '~/components/ui/textarea'
// 设置状态
const settings = ref<SettingRead>
const loading = ref(true)
const saving = ref(false)
// 表单值
const apiKeyValue = ref('')
const baseUrlValue = ref('')
const defaultModelValue = ref('__default__')
const gitProxyValue = ref('')
const showApiKey = ref(false)
// 跟踪用户是否修改了值
const apiKeyDirty = ref(false)
const baseUrlDirty = ref(false)
const defaultModelDirty = ref(false)
const gitProxyDirty = ref(false)
// 本页面管理的设置键（向量索引设置由 VectorIndexSettings 组件管理）
type ManagedSettingKey = SettingKey.ANTHROPIC_API_KEY | SettingKey.ANTHROPIC_BASE_URL | SettingKey.ANTHROPIC_MODEL | SettingKey.GIT_HTTP_PROXY
// 设置项元数据
const settingsMeta: Record<ManagedSettingKey, { label: string, description: string, placeholder: string }> = {
 [SettingKey.ANTHROPIC_API_KEY]: {
 label: 'API Key',
 description: '用于 Claude Code SDK 的 API 密钥，将加密存储',
 placeholder: 'sk-ant-...',
 },
 [SettingKey.ANTHROPIC_BASE_URL]: {
 label: 'Base URL',
 description: 'API 基础地址，用于代理或自定义端点（可选）',
 placeholder: 'https://api.anthropic.com',
 },
 [SettingKey.ANTHROPIC_MODEL]: {
 label: '默认模型',
 description: '用于所有未指定模型的调用，留空则使用内置默认值',
 placeholder: '如 claude-sonnet-4-20250514',
 },
 [SettingKey.GIT_HTTP_PROXY]: {
 label: 'Git 全局代理',
 description: '用于 Git 操作的默认 HTTP 代理（可选，仓库级配置优先）',
 placeholder: 'http://proxy.example.com:8080',
 },
}
// 加载设置
async function loadSettings {
 loading.value = true
 try {
 settings.value = await getAllSettings
 // 填充表单值
 const apiKeySetting = settings.value.find(s => s.key === SettingKey.ANTHROPIC_API_KEY)
 const baseUrlSetting = settings.value.find(s => s.key === SettingKey.ANTHROPIC_BASE_URL)
 const gitProxySetting = settings.value.find(s => s.key === SettingKey.GIT_HTTP_PROXY)
 // Base URL 直接使用返回的 value
 if (baseUrlSetting?.value) {
 baseUrlValue.value = baseUrlSetting.value
 }
 else {
 baseUrlValue.value = ''
 }
 // 默认模型
 const defaultModelSetting = settings.value.find(s => s.key === SettingKey.ANTHROPIC_MODEL)
 if (defaultModelSetting?.value) {
 defaultModelValue.value = defaultModelSetting.value
 }
 else {
 defaultModelValue.value = '__default__'
 }
 // Git Proxy
 if (gitProxySetting?.value) {
 gitProxyValue.value = gitProxySetting.value
 }
 else {
 gitProxyValue.value = ''
 }
 // API Key 使用遮罩值显示
 if (apiKeySetting?.has_value && apiKeySetting.masked_value) {
 apiKeyValue.value = apiKeySetting.masked_value
 }
 else {
 apiKeyValue.value = ''
 }
 // 重置脏标记
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 defaultModelDirty.value = false
 gitProxyDirty.value = false
 // 飞书 IM 配置
 const feishuAppIdSetting = settings.value.find(s => s.key === SettingKey.FEISHU_APP_ID)
 const feishuAppSecretSetting = settings.value.find(s => s.key === SettingKey.FEISHU_APP_SECRET)
 if (feishuAppIdSetting?.value) {
 feishuAppIdValue.value = feishuAppIdSetting.value
 }
 else {
 feishuAppIdValue.value = ''
 }
 if (feishuAppSecretSetting?.has_value && feishuAppSecretSetting.masked_value) {
 feishuAppSecretValue.value = feishuAppSecretSetting.masked_value
 }
 else {
 feishuAppSecretValue.value = ''
 }
 feishuAppIdDirty.value = false
 feishuAppSecretDirty.value = false
 }
 catch (error) {
 console.error('Failed to load settings:', error)
 toast.error('加载设置失败')
 }
 finally {
 loading.value = false
 }
}
// 保存所有设置
async function saveAllSettings {
 saving.value = true
 try {
 const promises: Promise<unknown> =
 // 保存 API Key（只有用户实际修改过才保存）
 if (apiKeyDirty.value && apiKeyValue.value.trim) {
 promises.push(updateSetting(SettingKey.ANTHROPIC_API_KEY, apiKeyValue.value.trim))
 }
 // 保存 Base URL（只有用户实际修改过才保存）
 if (baseUrlDirty.value && baseUrlValue.value.trim) {
 promises.push(updateSetting(SettingKey.ANTHROPIC_BASE_URL, baseUrlValue.value.trim))
 }
 // 保存默认模型（只有用户实际修改过才保存）
 if (defaultModelDirty.value) {
 const modelVal = defaultModelValue.value === '__default__' ? '': defaultModelValue.value.trim
 if (modelVal) {
 promises.push(updateSetting(SettingKey.ANTHROPIC_MODEL, modelVal))
 }
 else {
 promises.push(deleteSetting(SettingKey.ANTHROPIC_MODEL))
 }
 }
 // 保存 Git Proxy
 if (gitProxyDirty.value && gitProxyValue.value.trim) {
 promises.push(updateSetting(SettingKey.GIT_HTTP_PROXY, gitProxyValue.value.trim))
 }
 if (promises.length === 0) {
 toast.info('没有需要保存的更改')
 return
 }
 await Promise.all(promises)
 toast.success('设置已保存')
 await loadSettings
 }
 catch (error) {
 console.error('Failed to save settings:', error)
 toast.error('保存失败')
 }
 finally {
 saving.value = false
 }
}
// 删除设置
async function removeSetting(key: SettingKey) {
 saving.value = true
 try {
 await deleteSetting(key)
 toast.success('设置已删除')
 if (key === SettingKey.ANTHROPIC_API_KEY) {
 apiKeyValue.value = ''
 apiKeyDirty.value = false
 }
 else if (key === SettingKey.ANTHROPIC_BASE_URL) {
 baseUrlValue.value = ''
 baseUrlDirty.value = false
 }
 else if (key === SettingKey.ANTHROPIC_MODEL) {
 defaultModelValue.value = '__default__'
 defaultModelDirty.value = false
 }
 else if (key === SettingKey.GIT_HTTP_PROXY) {
 gitProxyValue.value = ''
 gitProxyDirty.value = false
 }
 await loadSettings
 }
 catch (error) {
 console.error('Failed to delete setting:', error)
 toast.error('删除失败')
 }
 finally {
 saving.value = false
 }
}
// 获取设置状态
function getSettingByKey(key: SettingKey): SettingRead | undefined {
 return settings.value.find(s => s.key === key)
}
// 处理 API Key 输入变更
function onApiKeyInput {
 apiKeyDirty.value = true
}
// 处理 Base URL 输入变更
function onBaseUrlInput {
 baseUrlDirty.value = true
}
// 处理默认模型输入变更
function onDefaultModelInput {
 defaultModelDirty.value = true
}
// 处理 Git Proxy 输入变更
function onGitProxyInput {
 gitProxyDirty.value = true
}
// 检查是否有未保存的更改
function hasUnsavedChanges: boolean {
 return apiKeyDirty.value || baseUrlDirty.value || defaultModelDirty.value || gitProxyDirty.value
}
// ===== 飞书 IM 配置 =====
const feishuAppIdValue = ref('')
const feishuAppSecretValue = ref('')
const feishuAppIdDirty = ref(false)
const feishuAppSecretDirty = ref(false)
const showFeishuAppSecret = ref(false)
const savingFeishuIM = ref(false)
// 飞书 IM 测试
const feishuTestReceiveId = ref('')
const feishuTestReceiveIdType = ref<'open_id' | 'chat_id'>('open_id')
const feishuTestMessage = ref('这是一条测试消息，来自 Friday AI Agent 配置测试。')
const testingFeishuIM = ref(false)
const feishuTestResult = ref<{ success: boolean; message: string } | null>(null)
function onFeishuAppIdInput {
 feishuAppIdDirty.value = true
}
function onFeishuAppSecretInput {
 feishuAppSecretDirty.value = true
}
function hasFeishuIMConfig: boolean {
 return getSettingByKey(SettingKey.FEISHU_APP_ID)?.has_value ?? false
}
async function saveFeishuIMConfig {
 if (!feishuAppIdValue.value.trim) {
 toast.error('请输入 App ID')
 return
 }
 const hasExistingSecret = getSettingByKey(SettingKey.FEISHU_APP_SECRET)?.has_value
 if (!feishuAppSecretValue.value.trim && !hasExistingSecret) {
 toast.error('请输入 App Secret')
 return
 }
 savingFeishuIM.value = true
 try {
 const promises: Promise<unknown> =
 if (feishuAppIdDirty.value && feishuAppIdValue.value.trim) {
 promises.push(updateSetting(SettingKey.FEISHU_APP_ID, feishuAppIdValue.value.trim))
 }
 if (feishuAppSecretDirty.value && feishuAppSecretValue.value.trim) {
 promises.push(updateSetting(SettingKey.FEISHU_APP_SECRET, feishuAppSecretValue.value.trim))
 }
 if (promises.length > 0) {
 await Promise.all(promises)
 toast.success('飞书 IM 配置已保存')
 feishuAppSecretValue.value = ''
 feishuAppIdDirty.value = false
 feishuAppSecretDirty.value = false
 await loadSettings
 }
 else {
 toast.info('没有需要保存的更改')
 }
 }
 catch (error) {
 console.error('Failed to save Feishu IM config:', error)
 toast.error('保存失败')
 }
 finally {
 savingFeishuIM.value = false
 }
}
async function removeFeishuIMConfig {
 savingFeishuIM.value = true
 try {
 await Promise.all([
 deleteSetting(SettingKey.FEISHU_APP_ID),
 deleteSetting(SettingKey.FEISHU_APP_SECRET),
 ])
 toast.success('飞书 IM 配置已删除')
 feishuAppIdValue.value = ''
 feishuAppSecretValue.value = ''
 feishuAppIdDirty.value = false
 feishuAppSecretDirty.value = false
 await loadSettings
 }
 catch (error) {
 console.error('Failed to delete Feishu IM config:', error)
 toast.error('删除失败')
 }
 finally {
 savingFeishuIM.value = false
 }
}
async function testFeishuIMConfig {
 if (!feishuTestReceiveId.value.trim) {
 toast.error(feishuTestReceiveIdType.value === 'chat_id' ? '请输入群聊 ID': '请输入用户 ID')
 return
 }
 testingFeishuIM.value = true
 feishuTestResult.value = null
 try {
 // 测试时只传接收者信息，app_id 和 app_secret 由后端从数据库获取
 const result = await testFeishuIM({
 receive_id: feishuTestReceiveId.value.trim,
 receive_id_type: feishuTestReceiveIdType.value,
 message: feishuTestMessage.value,
 })
 feishuTestResult.value = result
 if (result.success) {
 toast.success('消息已发送，请检查飞书')
 }
 else {
 toast.error(result.message)
 }
 }
 catch (error) {
 const message = error instanceof Error ? error.message: '测试失败'
 feishuTestResult.value = { success: false, message }
 toast.error(message)
 }
 finally {
 testingFeishuIM.value = false
 }
}
// 模型列表和测试相关
const models = ref<Model>
const loadingModels = ref(false)
const testDialogOpen = ref(false)
// 是否可以测试（已配置 API Key）
function canTest: boolean {
 return getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value ?? false
}
// 获取模型列表
async function fetchModels {
 if (!canTest)
 return
 loadingModels.value = true
 try {
 const response = await getModels({ source: 'system' })
 models.value = response.models
 }
 catch (error) {
 console.error('Failed to fetch models:', error)
 }
 finally {
 loadingModels.value = false
 }
}
// 打开测试对话框
function openTestDialog {
 testDialogOpen.value = true
}
// 监听设置加载完成后获取模型列表
watch( => loading.value, (isLoading) => {
 if (!isLoading && canTest) {
 fetchModels
 }
})
onMounted( => {
 loadSettings
})
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <div class="max-w-2xl mx-auto space-y-8 relative">
 <!-- 页面标题 -->
 <section class="text-center pt-8 pb-4">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--settings] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent mb-3">
 系统设置
 </h1>
 <p class="text-muted-foreground max-w-md mx-auto">
 配置全局的 Claude Code 设置，作为所有项目的默认值
 </p>
 </section>
 <LoadingState v-if="loading" variant="spinner" text="加载设置..." />
 <template v-else>
 <!-- 主配置区域 -->
 <div class="space-y-6">
 <!-- Claude Code 配置卡片 -->
 <section class="group relative">
 <!-- 悬浮光晕 -->
 <div class="absolute inset-0 bg-gradient-to-r from-primary/20 via-blue-500/20 to-cyan-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10" />
 <div class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden group-hover:border-primary/30 group-hover:shadow-lg group-hover:shadow-primary/5 transition-all duration-300">
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
 {{ settingsMeta[SettingKey.ANTHROPIC_API_KEY].label }}
 </Label>
 <span
 v-if="getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value"
 class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-600 bg-emerald-500/10 rounded-full"
 >
 <span class="icon-[lucide--check-circle]" />
 已配置
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ settingsMeta[SettingKey.ANTHROPIC_API_KEY].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="api-key"
 v-model="apiKeyValue":type="showApiKey ? 'text': 'password'":placeholder="settingsMeta[SettingKey.ANTHROPIC_API_KEY].placeholder"
 class="pl-10 pr-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onApiKeyInput"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="showApiKey = !showApiKey"
 >
 <span:class="showApiKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 <Button
 v-if="getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value"
 variant="outline"
 class=" hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
 @click="removeSetting(SettingKey.ANTHROPIC_API_KEY)"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 </div>
 <!-- Base URL 字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="base-url" class="text-base font-medium">
 {{ settingsMeta[SettingKey.ANTHROPIC_BASE_URL].label }}
 </Label>
 <span
 v-if="getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.value"
 class="text-xs text-muted-foreground"
 >
 已自定义
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ settingsMeta[SettingKey.ANTHROPIC_BASE_URL].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
 <Input
 id="base-url"
 v-model="baseUrlValue"
 type="url":placeholder="settingsMeta[SettingKey.ANTHROPIC_BASE_URL].placeholder"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onBaseUrlInput"
 />
 </div>
 <Button
 v-if="getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.has_value"
 variant="outline"
 class=" hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
 @click="removeSetting(SettingKey.ANTHROPIC_BASE_URL)"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 <p v-if="getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.value" class="text-sm text-muted-foreground">
 当前值: {{ getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.value }}
 </p>
 </div>
 <!-- 默认模型字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="default-model" class="text-base font-medium">
 {{ settingsMeta[SettingKey.ANTHROPIC_MODEL].label }}
 </Label>
 <span
 v-if="getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.value"
 class="text-xs text-muted-foreground"
 >
 已自定义
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ settingsMeta[SettingKey.ANTHROPIC_MODEL].description }}
 </p>
 <div class="flex gap-2">
 <div class="flex-1">
 <div v-if="loadingModels" class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 正在获取模型列表...
 </div>
 <Select v-else-if="models.length > 0" v-model="defaultModelValue" @update:model-value="onDefaultModelInput">
 <SelectTrigger class=" bg-muted/30 border-border/50">
 <SelectValue placeholder="选择默认模型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__default__">
 使用内置默认
 </SelectItem>
 <SelectItem
 v-for="model in models":key="model.id":value="model.id"
 >
 {{ model.name || model.id }}
 </SelectItem>
 </SelectContent>
 </Select>
 <div v-else class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--cpu] text-muted-foreground" />
 <Input
 id="default-model":model-value="defaultModelValue === '__default__' ? '': defaultModelValue":placeholder="settingsMeta[SettingKey.ANTHROPIC_MODEL].placeholder"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @update:model-value="(v: string) => { defaultModelValue = v || '__default__'; onDefaultModelInput }"
 />
 </div>
 </div>
 <Button
 v-if="canTest"
 variant="outline"
 size="icon"
 class=" w-11 shrink-0":disabled="loadingModels"
 @click="fetchModels"
 >
 <span
 class="icon-[lucide--refresh-cw]":class="loadingModels && 'animate-spin'"
 />
 </Button>
 <Button
 v-if="getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.has_value"
 variant="outline"
 class=" hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
 @click="removeSetting(SettingKey.ANTHROPIC_MODEL)"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 <p v-if="getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.value" class="text-sm text-muted-foreground">
 当前值: {{ getSettingByKey(SettingKey.ANTHROPIC_MODEL)?.value }}
 </p>
 </div>
 <!-- Git Proxy 字段 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="git-proxy" class="text-base font-medium">
 {{ settingsMeta[SettingKey.GIT_HTTP_PROXY].label }}
 </Label>
 <span
 v-if="getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.value"
 class="text-xs text-muted-foreground"
 >
 已配置
 </span>
 </div>
 <p class="text-sm text-muted-foreground">
 {{ settingsMeta[SettingKey.GIT_HTTP_PROXY].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--network] text-muted-foreground" />
 <Input
 id="git-proxy"
 v-model="gitProxyValue"
 type="url":placeholder="settingsMeta[SettingKey.GIT_HTTP_PROXY].placeholder"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onGitProxyInput"
 />
 </div>
 <Button
 v-if="getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.has_value"
 variant="outline"
 class=" hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
 @click="removeSetting(SettingKey.GIT_HTTP_PROXY)"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 <p v-if="getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.value" class="text-sm text-muted-foreground">
 当前值: {{ getSettingByKey(SettingKey.GIT_HTTP_PROXY)?.value }}
 </p>
 </div>
 </div>
 <!-- 保存按钮区域 -->
 <div class="flex justify-end gap-3 px-6 py-4 border-t border-border/50">
 <Button
 v-if="canTest"
 variant="outline"
 @click="openTestDialog"
 >
 <span class="icon-[lucide--flask-conical] mr-2" />
 连接测试
 </Button>
 <Button:disabled="saving || !hasUnsavedChanges"
 class="group/btn relative overflow-hidden"
 @click="saveAllSettings"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover/btn:translate-x-[100%] transition-transform duration-700" />
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 </div>
 </section>
 <!-- 说明卡片 -->
 <section class=" rounded-2xl border border-dashed border-border/50 bg-muted/20">
 <div class="flex items-start gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-muted to-muted/50 flex items-center justify-center">
 <span class="icon-[lucide--info] text-xl text-muted-foreground" />
 </div>
 <div class="space-y-2">
 <h3 class="font-medium">
 配置优先级说明
 </h3>
 <p class="text-sm text-muted-foreground">
 Claude Code 配置按以下优先级应用（高到低）：
 </p>
 <ol class="list-decimal list-inside space-y-1 text-sm text-muted-foreground ml-2">
 <li><strong class="text-foreground">项目级配置</strong> - 在项目设置中单独配置的值</li>
 <li><strong class="text-foreground">系统级配置</strong> - 在此页面配置的全局默认值</li>
 </ol>
 </div>
 </div>
 </section>
 <!-- 向量索引配置 -->
 <VectorIndexSettings />
 <!-- 飞书 IM 配置卡片 -->
 <section class="group relative">
 <!-- 悬浮光晕 -->
 <div class="absolute inset-0 bg-gradient-to-r from-blue-500/20 via-cyan-500/20 to-blue-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10" />
 <div class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden group-hover:border-blue-500/30 group-hover:shadow-lg group-hover:shadow-blue-500/5 transition-all duration-300">
 <!-- 卡片头部 -->
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-blue-500/5 to-cyan-500/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-blue-500/20 to-blue-500/10 flex items-center justify-center">
 <span class="icon-[lucide--message-circle] text-2xl text-blue-500" />
 </div>
 <div class="flex-1">
 <h2 class="text-lg font-semibold">
 飞书 IM 配置
 </h2>
 <p class="text-sm text-muted-foreground">
 用于 AI Agent 发送飞书消息（提问卡片、通知等）
 </p>
 </div>
 <span
 v-if="hasFeishuIMConfig"
 class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-600 bg-emerald-500/10 rounded-full"
 >
 <span class="icon-[lucide--check-circle]" />
 已配置
 </span>
 </div>
 <!-- 表单内容 -->
 <div class=" space-y-6">
 <!-- 说明 -->
 <div class="rounded-lg bg-blue-500/5 border border-blue-500/20 text-sm text-muted-foreground space-y-2">
 <p class="font-medium text-blue-600 flex items-center gap-2">
 <span class="icon-[lucide--info]" />
 配置说明
 </p>
 <p>用于 AI Agent 通过飞书发送消息和接收用户回复。</p>
 <p>需要在<strong>飞书开放平台</strong>创建自建应用，并开启消息权限和长连接模式。</p>
 </div>
 <!-- App ID -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="feishu-app-id" class="text-base font-medium">
 App ID
 </Label>
 </div>
 <p class="text-sm text-muted-foreground">
 飞书开放平台 → 应用管理 → 凭证与基础信息
 </p>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="feishu-app-id"
 v-model="feishuAppIdValue"
 placeholder="cli_xxxxxxxxxx"
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onFeishuAppIdInput"
 />
 </div>
 </div>
 <!-- App Secret -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <Label for="feishu-app-secret" class="text-base font-medium">
 App Secret
 </Label>
 <span
 v-if="getSettingByKey(SettingKey.FEISHU_APP_SECRET)?.has_value"
 class="text-xs text-emerald-600"
 >
 (已配置，留空则保持不变)
 </span>
 </div>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 id="feishu-app-secret"
 v-model="feishuAppSecretValue":type="showFeishuAppSecret ? 'text': 'password'":placeholder="getSettingByKey(SettingKey.FEISHU_APP_SECRET)?.has_value ? '••••••••••••••••': '输入 App Secret'"
 class="pl-10 pr-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onFeishuAppSecretInput"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="showFeishuAppSecret = !showFeishuAppSecret"
 >
 <span:class="showFeishuAppSecret ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 </div>
 </div>
 <!-- 保存按钮区域 -->
 <div class="flex justify-between px-6 py-4 border-t border-border/50">
 <Button
 v-if="hasFeishuIMConfig"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="savingFeishuIM"
 @click="removeFeishuIMConfig"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除配置
 </Button>
 <div v-else />
 <Button:disabled="savingFeishuIM || (!feishuAppIdDirty && !feishuAppSecretDirty)"
 @click="saveFeishuIMConfig"
 >
 <span v-if="savingFeishuIM" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存 IM 配置
 </Button>
 </div>
 <!-- 测试区域 -->
 <div v-if="hasFeishuIMConfig || feishuAppIdValue.trim" class="px-6 py-4 border-t border-border/50 space-y-4 bg-muted/20">
 <div class="flex items-center gap-2 text-sm font-medium">
 <span class="icon-[lucide--flask-conical] text-amber-500" />
 测试消息发送
 </div>
 <div class="space-y-3">
 <div class="space-y-1.5">
 <Label class="text-sm">发送类型</Label>
 <div class="flex gap-4">
 <label class="flex items-center gap-2 cursor-pointer">
 <input
 v-model="feishuTestReceiveIdType"
 type="radio"
 value="open_id"
 class="accent-primary"
 >
 <span class="text-sm">用户 (open_id)</span>
 </label>
 <label class="flex items-center gap-2 cursor-pointer">
 <input
 v-model="feishuTestReceiveIdType"
 type="radio"
 value="chat_id"
 class="accent-primary"
 >
 <span class="text-sm">群聊 (chat_id)</span>
 </label>
 </div>
 </div>
 <div class="space-y-1.5">
 <Label class="text-sm">{{ feishuTestReceiveIdType === 'chat_id' ? '群聊 ID': '用户 ID' }}</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground":class="feishuTestReceiveIdType === 'chat_id' ? 'icon-[lucide--users]': 'icon-[lucide--user]'" />
 <Input
 v-model="feishuTestReceiveId":placeholder="feishuTestReceiveIdType === 'chat_id' ? 'oc_xxxxxxxxxx': 'ou_xxxxxxxxxx'"
 class="pl-10 font-mono text-sm bg-background border-border/50"
 />
 </div>
 <p class="text-xs text-muted-foreground">
 {{ feishuTestReceiveIdType === 'chat_id' ? '获取方式：把机器人拉入群聊后，从群设置中复制群链接获取': '获取方式：飞书管理后台 → 成员管理 → 点击成员 → 复制 Open ID' }}
 </p>
 </div>
 <div class="space-y-1.5">
 <Label class="text-sm">测试消息</Label>
 <Textarea
 v-model="feishuTestMessage"
 rows="2"
 class="text-sm resize-none bg-background border-border/50"
 />
 </div>
 <div class="flex items-center gap-3">
 <Button
 variant="outline"
 size="sm":disabled="testingFeishuIM"
 @click="testFeishuIMConfig"
 >
 <span v-if="testingFeishuIM" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--send] mr-2" />
 发送测试消息
 </Button>
 <!-- 测试结果 -->
 <div
 v-if="feishuTestResult"
 class="flex-1 rounded-lg px-3 py-2 text-xs":class="feishuTestResult.success ? 'bg-emerald-500/10 text-emerald-600': 'bg-destructive/10 text-destructive'"
 >
 <span:class="feishuTestResult.success ? 'icon-[lucide--check-circle]': 'icon-[lucide--x-circle]'" class="mr-1.5" />
 {{ feishuTestResult.message }}
 </div>
 </div>
 </div>
 </div>
 </div>
 </section>
 </div>
 </template>
 <!-- 测试对话框 -->
 <ClaudeTestDialog
 v-model:open="testDialogOpen"
 source="system"
 />
 </div>
 </div>
</template>
