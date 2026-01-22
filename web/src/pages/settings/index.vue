<script setup lang="ts">
import type { SettingRead } from '~/api/settings'
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import {
 deleteSetting,
 getAllSettings,
 SettingKey,
 updateSetting,
} from '~/api/settings'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
const router = useRouter
// 设置状态
const settings = ref<SettingRead>
const loading = ref(true)
const saving = ref(false)
// 表单值
const apiKeyValue = ref('')
const baseUrlValue = ref('')
const showApiKey = ref(false)
// 跟踪用户是否修改了值
const apiKeyDirty = ref(false)
const baseUrlDirty = ref(false)
// 设置项元数据
const settingsMeta: Record<SettingKey, { label: string, description: string, placeholder: string }> = {
 [SettingKey.ANTHROPIC_API_KEY]: {
 label: 'Anthropic API Key',
 description: '用于 Claude Code SDK 的 API 密钥，将加密存储',
 placeholder: 'sk-ant-...',
 },
 [SettingKey.ANTHROPIC_BASE_URL]: {
 label: 'Anthropic Base URL',
 description: 'API 基础地址，用于代理或自定义端点',
 placeholder: 'https://api.anthropic.com',
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
 // Base URL 直接使用返回的 value
 if (baseUrlSetting?.value) {
 baseUrlValue.value = baseUrlSetting.value
 }
 else {
 baseUrlValue.value = ''
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
// 检查是否有未保存的更改
function hasUnsavedChanges: boolean {
 return apiKeyDirty.value || baseUrlDirty.value
}
onMounted( => {
 loadSettings
})
</script>
<template>
 <div class="max-w-3xl mx-auto space-y-8">
 <!-- 页面标题 -->
 <div class="flex items-start gap-3">
 <div class="size-9 flex items-center justify-center rounded-lg bg-gradient-to-br from-gray-500/20 to-slate-500/10">
 <span class="icon-[lucide--settings] text-xl text-gray-500" />
 </div>
 <div class="space-y-1">
 <h1 class="text-2xl font-bold">系统设置</h1>
 <p class="text-muted-foreground">
 配置全局的 Claude Code 设置，这些设置将作为所有项目的默认值
 </p>
 </div>
 </div>
 <LoadingState v-if="loading" variant="spinner" text="加载设置..." />
 <template v-else>
 <!-- Claude Code 配置 -->
 <div class="relative">
 <!-- 卡片光晕 -->
 <div class="absolute -inset-1 bg-gradient-to-r from-primary/10 via-secondary/10 to-primary/10 rounded-3xl blur-xl opacity-70" />
 <!-- 卡片主体 -->
 <div class="relative bg-card/80 backdrop-blur-sm rounded-2xl border border-border/50 overflow-hidden">
 <!-- 标题区域 -->
 <div class=" border-b border-border/50 bg-gradient-to-r from-primary/5 to-secondary/5">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--bot] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">Claude Code 配置</h2>
 <p class="text-sm text-muted-foreground">
 配置 Anthropic API 凭证，用于 AI 开发任务
 </p>
 </div>
 </div>
 </div>
 <!-- 配置内容 -->
 <div class=" space-y-6">
 <!-- API Key -->
 <div class="space-y-3">
 <Label for="api-key" class="text-base">{{ settingsMeta[SettingKey.ANTHROPIC_API_KEY].label }}</Label>
 <p class="text-sm text-muted-foreground">
 {{ settingsMeta[SettingKey.ANTHROPIC_API_KEY].description }}
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="api-key"
 v-model="apiKeyValue":type="showApiKey ? 'text': 'password'":placeholder="settingsMeta[SettingKey.ANTHROPIC_API_KEY].placeholder"
 class="pl-10 pr-10 bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onApiKeyInput"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
 @click="showApiKey = !showApiKey"
 >
 <span:class="showApiKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 <Button
 v-if="getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
 @click="removeSetting(SettingKey.ANTHROPIC_API_KEY)"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 <p v-if="getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value" class="text-sm text-emerald-600 flex items-center gap-1">
 <span class="icon-[lucide--check-circle]" />
 已配置 API Key
 </p>
 </div>
 <!-- Base URL -->
 <div class="space-y-3">
 <Label for="base-url" class="text-base">{{ settingsMeta[SettingKey.ANTHROPIC_BASE_URL].label }}</Label>
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
 class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onBaseUrlInput"
 />
 </div>
 <Button
 v-if="getSettingByKey(SettingKey.ANTHROPIC_BASE_URL)?.has_value"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
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
 <!-- 统一保存按钮 -->
 <div class="flex justify-end pt-4 border-t border-border/50">
 <Button:disabled="saving || !hasUnsavedChanges"
 class="group relative overflow-hidden"
 @click="saveAllSettings"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 </div>
 </div>
 </div>
 <!-- 说明卡片 -->
 <div class=" rounded-2xl border border-dashed border-border/50 bg-muted/20">
 <div class="flex items-start gap-3">
 <span class="icon-[lucide--info] text-xl text-muted-foreground flex-shrink-0 mt-0.5" />
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
 </div>
 </template>
 </div>
</template>
