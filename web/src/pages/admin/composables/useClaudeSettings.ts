import type { Model } from '~/api/chat'
import type { SettingRead } from '~/api/settings'
import { computed, onMounted, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { getModels } from '~/api/chat'
import {
 deleteSetting,
 getAllSettings,
 SettingKey,
 updateSetting,
} from '~/api/settings'
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
export function useClaudeSettings {
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
 // 模型列表和测试相关
 const models = ref<Model>
 const loadingModels = ref(false)
 const testDialogOpen = ref(false)
 // 获取设置状态
 function getSettingByKey(key: SettingKey): SettingRead | undefined {
 return settings.value.find(s => s.key === key)
 }
 // 是否有未保存的更改
 const hasUnsavedChanges = computed( => {
 return apiKeyDirty.value || baseUrlDirty.value || defaultModelDirty.value || gitProxyDirty.value
 })
 // 是否可以测试（已配置 API Key）
 function canTest: boolean {
 return getSettingByKey(SettingKey.ANTHROPIC_API_KEY)?.has_value ?? false
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
 baseUrlValue.value = baseUrlSetting?.value ?? ''
 const defaultModelSetting = settings.value.find(s => s.key === SettingKey.ANTHROPIC_MODEL)
 defaultModelValue.value = defaultModelSetting?.value ?? '__default__'
 gitProxyValue.value = gitProxySetting?.value ?? ''
 // API Key 直接显示值
 apiKeyValue.value = (apiKeySetting?.has_value && apiKeySetting.value) ? apiKeySetting.value: ''
 // 重置脏标记
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 defaultModelDirty.value = false
 gitProxyDirty.value = false
 }
 catch {
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
 if (apiKeyDirty.value && apiKeyValue.value.trim) {
 promises.push(updateSetting(SettingKey.ANTHROPIC_API_KEY, apiKeyValue.value.trim))
 }
 if (baseUrlDirty.value && baseUrlValue.value.trim) {
 promises.push(updateSetting(SettingKey.ANTHROPIC_BASE_URL, baseUrlValue.value.trim))
 }
 if (defaultModelDirty.value) {
 const modelVal = defaultModelValue.value === '__default__' ? '': defaultModelValue.value.trim
 if (modelVal) {
 promises.push(updateSetting(SettingKey.ANTHROPIC_MODEL, modelVal))
 }
 else {
 promises.push(deleteSetting(SettingKey.ANTHROPIC_MODEL))
 }
 }
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
 catch {
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
 catch {
 toast.error('删除失败')
 }
 finally {
 saving.value = false
 }
 }
 // 输入变更处理
 function onApiKeyInput {
 apiKeyDirty.value = true
 }
 function onBaseUrlInput {
 baseUrlDirty.value = true
 }
 function onDefaultModelInput {
 defaultModelDirty.value = true
 }
 function onGitProxyInput {
 gitProxyDirty.value = true
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
 catch {
 // intentionally ignored
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
 return {
 settings,
 loading,
 saving,
 apiKeyValue,
 baseUrlValue,
 defaultModelValue,
 gitProxyValue,
 showApiKey,
 apiKeyDirty,
 baseUrlDirty,
 defaultModelDirty,
 gitProxyDirty,
 models,
 loadingModels,
 testDialogOpen,
 settingsMeta,
 hasUnsavedChanges,
 getSettingByKey,
 canTest,
 loadSettings,
 saveAllSettings,
 removeSetting,
 onApiKeyInput,
 onBaseUrlInput,
 onDefaultModelInput,
 onGitProxyInput,
 fetchModels,
 openTestDialog,
 }
}
