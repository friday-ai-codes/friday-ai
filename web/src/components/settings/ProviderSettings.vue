<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { toast } from 'vue-sonner'
import { getAllSettings, SettingKey, updateSetting } from '~/api/settings'
import type { SettingRead } from '~/api/settings'
import ProviderIcon from '~/components/provider/ProviderIcon.vue'
import { PROVIDER_REGISTRY } from '~/types/provider'
import type { ProviderType } from '~/types/provider'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
/** Tab 短标签名映射 */
const TAB_LABELS: Record<ProviderType, string> = {
 'anthropic': 'Claude',
 'openai-responses': 'Responses',
 'openai-codex-responses': 'Codex',
 'openai-completions': 'Completions',
 'google-vertex': 'Vertex',
 'google-gemini-cli': 'Gemini',
 'google-antigravity': 'Antigravity',
}
/** Provider 到 SettingKey 的凭据映射 */
interface CredentialMapping {
 apiKeySettingKey: SettingKey | null
 baseUrlSettingKey: SettingKey | null
 sharedWith?: string // 共享提示文字
 useTextarea?: boolean // 是否用 Textarea（如 service account JSON）
}
const CREDENTIAL_MAP: Record<ProviderType, CredentialMapping> = {
 'anthropic': {
 apiKeySettingKey: SettingKey.ANTHROPIC_API_KEY,
 baseUrlSettingKey: SettingKey.ANTHROPIC_BASE_URL,
 sharedWith: '已在上方「Claude Code 配置」中管理',
 },
 'openai-responses': {
 apiKeySettingKey: SettingKey.OPENAI_API_KEY,
 baseUrlSettingKey: null,
 sharedWith: '此 API Key 同时用于 OpenAI Responses、Codex、Completions',
 },
 'openai-codex-responses': {
 apiKeySettingKey: SettingKey.OPENAI_API_KEY,
 baseUrlSettingKey: null,
 sharedWith: '此 API Key 同时用于 OpenAI Responses、Codex、Completions',
 },
 'openai-completions': {
 apiKeySettingKey: SettingKey.OPENAI_API_KEY,
 baseUrlSettingKey: null,
 sharedWith: '此 API Key 同时用于 OpenAI Responses、Codex、Completions',
 },
 'google-vertex': {
 apiKeySettingKey: SettingKey.GOOGLE_SERVICE_ACCOUNT_JSON,
 baseUrlSettingKey: null,
 useTextarea: true,
 sharedWith: '使用 Service Account JSON 凭证',
 },
 'google-gemini-cli': {
 apiKeySettingKey: SettingKey.GOOGLE_API_KEY,
 baseUrlSettingKey: null,
 sharedWith: '此 API Key 同时用于 Google Gemini 和 Antigravity',
 },
 'google-antigravity': {
 apiKeySettingKey: SettingKey.GOOGLE_API_KEY,
 baseUrlSettingKey: null,
 sharedWith: '此 API Key 同时用于 Google Gemini 和 Antigravity',
 },
}
// 加载状态
const loading = ref(true)
const settings = ref<SettingRead>
// 各 SettingKey 的表单状态
const formState = reactive<Record<string, { value: string, dirty: boolean, saving: boolean }>>({})
// 需要管理的唯一 SettingKey 集合
const managedKeys = [
 SettingKey.OPENAI_API_KEY,
 SettingKey.GOOGLE_API_KEY,
 SettingKey.GOOGLE_SERVICE_ACCOUNT_JSON,
]
function initFormState {
 for (const key of managedKeys) {
 const setting = settings.value.find(s => s.key === key)
 formState[key] = {
 value: setting?.has_value && setting.masked_value ? setting.masked_value: '',
 dirty: false,
 saving: false,
 }
 }
}
async function loadSettings {
 loading.value = true
 try {
 settings.value = await getAllSettings
 initFormState
 }
 catch {
 toast.error('加载 Provider 设置失败')
 }
 finally {
 loading.value = false
 }
}
function hasValue(key: SettingKey): boolean {
 return settings.value.find(s => s.key === key)?.has_value ?? false
}
function onInput(key: string) {
 if (formState[key]) {
 formState[key].dirty = true
 }
}
async function saveKey(key: SettingKey) {
 const state = formState[key]
 if (!state || !state.dirty || !state.value.trim) return
 state.saving = true
 try {
 await updateSetting(key, state.value.trim)
 toast.success('设置已保存')
 state.dirty = false
 // 刷新设置
 settings.value = await getAllSettings
 // 更新表单值为遮罩值
 const updated = settings.value.find(s => s.key === key)
 if (updated?.has_value && updated.masked_value) {
 state.value = updated.masked_value
 }
 }
 catch {
 toast.error('保存失败')
 }
 finally {
 state.saving = false
 }
}
function getCredentialMapping(provider: ProviderType): CredentialMapping {
 return CREDENTIAL_MAP[provider]
}
onMounted( => {
 loadSettings
})
</script>
<template>
 <section class="group relative">
 <!-- 悬浮光晕 -->
 <div class="absolute inset-0 bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-amber-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-500 rounded-2xl blur-xl -z-10" />
 <div class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden group-hover:border-amber-500/30 group-hover:shadow-lg group-hover:shadow-amber-500/5 transition-all duration-300">
 <!-- 卡片头部 -->
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-amber-500/20 to-amber-500/10 flex items-center justify-center">
 <span class="icon-[lucide--cpu] text-2xl text-amber-600" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 模型提供商配置
 </h2>
 <p class="text-sm text-muted-foreground">
 多 Provider API 凭证配置，用于 Chat AI
 </p>
 </div>
 </div>
 <!-- Tab 内容 -->
 <div class="">
 <div v-if="loading" class="flex items-center justify-center py-8 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin mr-2" />
 加载中...
 </div>
 <Tabs v-else default-value="anthropic">
 <TabsList class="w-full justify-start overflow-x-auto">
 <TabsTrigger
 v-for="provider in PROVIDER_REGISTRY":key="provider.type":value="provider.type"
 class="flex items-center gap-1.5 text-xs"
 >
 <ProviderIcon:provider="provider.type" size="sm" />
 {{ TAB_LABELS[provider.type] }}
 </TabsTrigger>
 </TabsList>
 <TabsContent
 v-for="provider in PROVIDER_REGISTRY":key="provider.type":value="provider.type"
 class="mt-4 space-y-4"
 >
 <!-- 共享提示 -->
 <div
 v-if="getCredentialMapping(provider.type).sharedWith"
 class="rounded-lg bg-muted/30 border border-border/50 px-4 py-3 text-sm text-muted-foreground flex items-start gap-2"
 >
 <span class="icon-[lucide--info] w-4 mt-0.5 shrink-0" />
 <span>{{ getCredentialMapping(provider.type).sharedWith }}</span>
 </div>
 <!-- Anthropic 特殊处理：已在 Claude Code 卡片管理 -->
 <template v-if="provider.type === 'anthropic'">
 <div class="text-sm text-muted-foreground py-4 text-center">
 Anthropic API 凭证由上方「Claude Code 配置」统一管理
 </div>
 </template>
 <!-- 其他 Provider：API Key / Service Account JSON 输入 -->
 <template v-else>
 <div
 v-if="getCredentialMapping(provider.type).apiKeySettingKey && formState[getCredentialMapping(provider.type).apiKeySettingKey!]"
 class="space-y-3"
 >
 <div class="flex items-center justify-between">
 <Label class="text-sm font-medium">
 {{ getCredentialMapping(provider.type).useTextarea ? 'Service Account JSON': 'API Key' }}
 </Label>
 <span
 v-if="hasValue(getCredentialMapping(provider.type).apiKeySettingKey!)"
 class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-emerald-600 bg-emerald-500/10 rounded-full"
 >
 <span class="icon-[lucide--check-circle]" />
 已配置
 </span>
 </div>
 <!-- Textarea 用于 Service Account JSON -->
 <Textarea
 v-if="getCredentialMapping(provider.type).useTextarea"
 v-model="formState[getCredentialMapping(provider.type).apiKeySettingKey!].value"
 rows="4"
 placeholder="粘贴 Service Account JSON..."
 class="font-mono text-xs bg-muted/30 border-border/50 resize-none"
 @input="onInput(getCredentialMapping(provider.type).apiKeySettingKey!)"
 />
 <!-- Input 用于 API Key -->
 <div v-else class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 v-model="formState[getCredentialMapping(provider.type).apiKeySettingKey!].value"
 type="password"
 placeholder="输入 API Key..."
 class="pl-10 font-mono text-sm bg-muted/30 border-border/50 focus:border-primary/50"
 @input="onInput(getCredentialMapping(provider.type).apiKeySettingKey!)"
 />
 </div>
 <!-- 保存按钮 -->
 <div class="flex justify-end">
 <Button
 size="sm":disabled="!formState[getCredentialMapping(provider.type).apiKeySettingKey!].dirty || formState[getCredentialMapping(provider.type).apiKeySettingKey!].saving"
 @click="saveKey(getCredentialMapping(provider.type).apiKeySettingKey!)"
 >
 <span
 v-if="formState[getCredentialMapping(provider.type).apiKeySettingKey!].saving"
 class="icon-[lucide--loader-circle] animate-spin mr-2"
 />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存
 </Button>
 </div>
 </div>
 </template>
 </TabsContent>
 </Tabs>
 </div>
 </div>
 </section>
</template>
