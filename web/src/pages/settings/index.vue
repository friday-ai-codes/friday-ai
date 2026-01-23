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
 updateSetting,
} from '~/api/settings'
import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import LoadingState from '~/components/common/LoadingState.vue'
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
// 设置状态
const settings = ref<SettingRead>
const loading = ref(true)
const saving = ref(false)
// 表单值
const apiKeyValue = ref('')
const baseUrlValue = ref('')
const gitProxyValue = ref('')
const showApiKey = ref(false)
// 跟踪用户是否修改了值
const apiKeyDirty = ref(false)
const baseUrlDirty = ref(false)
const gitProxyDirty = ref(false)
// 设置项元数据
const settingsMeta: Record<SettingKey, { label: string, description: string, placeholder: string }> = {
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
 gitProxyDirty.value = false
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
// 处理 Git Proxy 输入变更
function onGitProxyInput {
 gitProxyDirty.value = true
}
// 检查是否有未保存的更改
function hasUnsavedChanges: boolean {
 return apiKeyDirty.value || baseUrlDirty.value || gitProxyDirty.value
}
// 模型选择和测试相关
const models = ref<Model>
const selectedModel = ref('')
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
 const firstModel = models.value[0]
 if (firstModel && !selectedModel.value) {
 selectedModel.value = firstModel.id
 }
 }
 catch (error) {
 console.error('Failed to fetch models:', error)
 // 不显示错误，用户可以手动输入模型名称
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
 <h2 class="text-lg font-semibold">Claude Code 配置</h2>
 <p class="text-sm text-muted-foreground">Anthropic API 凭证，用于 AI 开发任务</p>
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
 <div class="flex justify-end px-6 py-4 border-t border-border/50">
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
 <!-- 连接测试卡片 -->
 <section v-if="canTest" class="group relative">
 <!-- 悬浮光晕 -->
 <div class="absolute inset-0 bg-gradient-to-r from-emerald-500/20 via-cyan-500/20 to-blue-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10" />
 <div class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden group-hover:border-emerald-500/30 group-hover:shadow-lg group-hover:shadow-emerald-500/5 transition-all duration-300">
 <!-- 装饰性顶部条纹 -->
 <div class=" bg-gradient-to-r from-emerald-500 via-cyan-500 to-blue-500" />
 <!-- 标题区域 -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-emerald-500/20 to-emerald-500/10 flex items-center justify-center">
 <span class="icon-[lucide--flask-conical] text-2xl text-emerald-500" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">连接测试</h2>
 <p class="text-sm text-muted-foreground">验证 API 配置是否正确</p>
 </div>
 </div>
 <button:disabled="loadingModels"
 class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground bg-muted/50 hover:bg-muted rounded-lg transition-all duration-200 disabled:opacity-50 cursor-pointer"
 @click="fetchModels"
 >
 <span
 class="icon-[lucide--refresh-cw]":class="loadingModels && 'animate-spin'"
 />
 刷新
 </button>
 </div>
 <div class="">
 <!-- 加载状态 -->
 <div v-if="loadingModels" class="flex items-center justify-center gap-3 py-8 bg-muted/30 rounded-xl border border-dashed border-border/50">
 <div class="relative">
 <div class="absolute inset-0 bg-primary/20 rounded-full blur animate-pulse" />
 <span class="relative icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 </div>
 <span class="text-sm text-muted-foreground">正在获取可用模型...</span>
 </div>
 <!-- 模型选择 -->
 <div v-else class="space-y-4">
 <div class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--cpu]" />
 <span>选择测试模型</span>
 </div>
 <div class="flex gap-3">
 <Select v-if="models.length > 0" v-model="selectedModel" class="flex-1">
 <SelectTrigger class=" bg-muted/30 border-border/50">
 <SelectValue placeholder="选择测试模型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="model in models":key="model.id":value="model.id"
 >
 {{ model.name || model.id }}
 </SelectItem>
 </SelectContent>
 </Select>
 <div v-else class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--type] text-muted-foreground" />
 <Input
 v-model="selectedModel"
 placeholder="输入模型名称，如 claude-sonnet-4-20250514"
 class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <Button:disabled="!selectedModel"
 class=" bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white shadow-lg shadow-emerald-500/25 transition-all duration-300 disabled:opacity-50 disabled:shadow-none group/btn"
 @click="openTestDialog"
 >
 <span class="icon-[lucide--play] mr-2 group-hover/btn:scale-110 transition-transform duration-200" />
 开始测试
 </Button>
 </div>
 </div>
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
 <h3 class="font-medium">配置优先级说明</h3>
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
