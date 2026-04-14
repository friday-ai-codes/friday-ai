<script setup lang="ts">
import type { Model } from '~/api/chat'
import type { ClaudeConfigCreate, ClaudeConfigRead } from '~/api/settings'
import { useHead } from '@vueuse/head'
/**
 * 项目 Claude 配置页面
 * 用于配置项目的 Claude Code 设置
 */
import { computed, onMounted, ref, watch } from 'vue'
import { getModels } from '~/api/chat'
import {
 deleteProjectClaudeConfig,
 getProjectClaudeConfig,
 updateProjectClaudeConfig,
} from '~/api/settings'
import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Badge } from '~/components/ui/badge'
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
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
const route = useRoute('/projects/[id]/claude')
const router = useRouter
const projectsStore = useProjectsStore
const projectId = computed( => route.params.id)
const { handleError } = useErrorHandler
const { success, info } = useToast
useHead({
 title: 'Claude 配置 - Friday AI',
})
// 加载数据
const loading = ref(true)
const saving = ref(false)
const claudeConfig = ref<ClaudeConfigRead | null>(null)
// 表单值
const apiKeyValue = ref('')
const baseUrlValue = ref('')
const defaultModelValue = ref('__default__')
const showApiKey = ref(false)
// 跟踪用户是否修改了值
const apiKeyDirty = ref(false)
const baseUrlDirty = ref(false)
const defaultModelDirty = ref(false)
async function loadData {
 loading.value = true
 try {
 await projectsStore.fetchProject(projectId.value)
 try {
 claudeConfig.value = await getProjectClaudeConfig(projectId.value)
 baseUrlValue.value = claudeConfig.value.base_url || ''
 defaultModelValue.value = claudeConfig.value.default_model || '__default__'
 apiKeyValue.value = ''
 }
 catch {
 claudeConfig.value = null
 }
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 defaultModelDirty.value = false
 }
 catch (e: unknown) {
 handleError(e, '加载配置')
 }
 finally {
 loading.value = false
 }
}
onMounted(loadData)
const project = computed( => projectsStore.currentProject)
// 配置来源标签
const sourceLabel = computed( => {
 if (!claudeConfig.value)
 return null
 switch (claudeConfig.value.source) {
 case 'project':
 return { text: '项目配置', variant: 'default' as const }
 case 'system':
 return { text: '系统默认', variant: 'secondary' as const }
 case 'environment':
 return { text: '环境变量', variant: 'outline' as const }
 default:
 return null
 }
})
// 处理输入变更
function onApiKeyInput {
 apiKeyDirty.value = true
}
function onBaseUrlInput {
 baseUrlDirty.value = true
}
function onDefaultModelChange {
 defaultModelDirty.value = true
}
// 检查是否有未保存的更改
function hasUnsavedChanges: boolean {
 return apiKeyDirty.value || baseUrlDirty.value || defaultModelDirty.value
}
// 保存配置
async function saveConfig {
 saving.value = true
 try {
 const config: ClaudeConfigCreate = {}
 if (apiKeyDirty.value && apiKeyValue.value.trim) {
 config.api_key = apiKeyValue.value.trim
 }
 if (baseUrlDirty.value) {
 config.base_url = baseUrlValue.value.trim || undefined
 }
 if (defaultModelDirty.value) {
 const modelVal = defaultModelValue.value === '__default__' ? '': defaultModelValue.value.trim
 config.default_model = modelVal || undefined
 }
 if (!config.api_key && config.base_url === undefined && config.default_model === undefined) {
 info('没有需要保存的更改')
 return
 }
 claudeConfig.value = await updateProjectClaudeConfig(projectId.value, config)
 apiKeyValue.value = ''
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 defaultModelDirty.value = false
 success('配置已保存')
 }
 catch (e: unknown) {
 handleError(e, '保存配置')
 }
 finally {
 saving.value = false
 }
}
// 删除配置
async function removeConfig {
 saving.value = true
 try {
 await deleteProjectClaudeConfig(projectId.value)
 claudeConfig.value = null
 apiKeyValue.value = ''
 baseUrlValue.value = ''
 defaultModelValue.value = '__default__'
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 defaultModelDirty.value = false
 success('配置已删除，将使用系统默认值')
 await loadData
 }
 catch (e: unknown) {
 handleError(e, '删除配置')
 }
 finally {
 saving.value = false
 }
}
// 模型列表和测试相关
const models = ref<Model>
const loadingModels = ref(false)
const testDialogOpen = ref(false)
// 是否可以测试（已配置 API Key）
function canTest: boolean {
 return claudeConfig.value?.has_api_key ?? false
}
// 获取模型列表
async function fetchModels {
 if (!canTest)
 return
 loadingModels.value = true
 try {
 const response = await getModels({
 source: 'project',
 project_id: Number(projectId.value),
 })
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
// 监听配置加载完成后获取模型列表
watch( => loading.value, (isLoading) => {
 if (!isLoading && canTest) {
 fetchModels
 }
})
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-8">
 <!-- 返回按钮 -->
 <RouterLink:to="`/projects/${projectId}`"
 class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors"
 >
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回项目详情
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="2" />
 <template v-else-if="project">
 <!-- 页面标题 -->
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--bot] text-2xl text-orange-500" />
 </div>
 <div>
 <h1 class="text-2xl font-bold">
 Claude 配置
 </h1>
 <p class="text-sm text-muted-foreground">
 配置 {{ project.name }} 的 Claude Code 设置
 </p>
 </div>
 </div>
 </div>
 <!-- 配置表单 -->
 <div class="relative">
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <h3 class="text-sm font-semibold">
 <span class="icon-[lucide--bot] text-primary" />
 项目级配置
 </h3>
 <p class="text-xs text-muted-foreground mt-1">
 为此项目单独配置 Claude Code，将覆盖系统默认设置
 </p>
 </div>
 <div class=" space-y-4">
 <!-- API Key -->
 <div class="space-y-3">
 <Label for="api-key" class="text-base">Anthropic API Key</Label>
 <p class="text-sm text-muted-foreground">
 为此项目单独配置的 API 密钥，将覆盖系统默认值
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 id="api-key"
 v-model="apiKeyValue":type="showApiKey ? 'text': 'password'"
 placeholder="sk-ant-..."
 class="pl-10 pr-10 bg-muted/30 border-border/50 focus:border-orange-500/50"
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
 </div>
 <p v-if="claudeConfig?.has_api_key" class="text-sm text-emerald-600 flex items-center gap-2">
 <span class="icon-[lucide--check-circle]" />
 已配置 API Key
 <Badge v-if="sourceLabel":variant="sourceLabel.variant">
 {{ sourceLabel.text }}
 </Badge>
 </p>
 </div>
 <!-- Base URL -->
 <div class="space-y-3">
 <Label for="base-url" class="text-base">Anthropic Base URL</Label>
 <p class="text-sm text-muted-foreground">
 API 基础地址，用于代理或自定义端点
 </p>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground" />
 <Input
 id="base-url"
 v-model="baseUrlValue"
 type="url"
 placeholder="https://api.anthropic.com"
 class="pl-10 bg-muted/30 border-border/50 focus:border-orange-500/50"
 @input="onBaseUrlInput"
 />
 </div>
 <p v-if="claudeConfig?.base_url" class="text-sm text-muted-foreground">
 当前值: {{ claudeConfig.base_url }}
 </p>
 </div>
 <!-- 默认模型 -->
 <div class="space-y-3">
 <Label for="default-model" class="text-base">默认模型</Label>
 <p class="text-sm text-muted-foreground">
 用于所有未指定模型的调用，留空则使用系统默认模型
 </p>
 <div class="flex gap-2">
 <div class="flex-1">
 <div v-if="loadingModels" class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 正在获取模型列表...
 </div>
 <Select v-else-if="models.length > 0" v-model="defaultModelValue" @update:model-value="onDefaultModelChange">
 <SelectTrigger class=" bg-muted/30 border-border/50">
 <SelectValue placeholder="选择默认模型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__default__">
 使用系统默认
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
 id="default-model":model-value="defaultModelValue === '__default__' ? '': defaultModelValue"
 placeholder="如 claude-sonnet-4-20250514"
 class="pl-10 bg-muted/30 border-border/50 focus:border-orange-500/50"
 @update:model-value="(v: string | number) => { defaultModelValue = String(v) || '__default__'; onDefaultModelChange }"
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
 class="icon-[lucide--refresh-cw]":class="[loadingModels && 'animate-spin']"
 />
 </Button>
 </div>
 <p v-if="claudeConfig?.default_model" class="text-sm text-muted-foreground">
 当前值: {{ claudeConfig.default_model }}
 </p>
 </div>
 <!-- 操作按钮 -->
 <div class="flex justify-between items-center pt-4 border-t border-border/50">
 <Button
 v-if="claudeConfig?.source === 'project'"
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="saving"
 @click="removeConfig"
 >
 <span class="icon-[lucide--trash-2] mr-2" />
 删除项目配置
 </Button>
 <div v-else />
 <div class="flex items-center gap-3">
 <Button
 v-if="canTest"
 variant="outline"
 @click="openTestDialog"
 >
 <span class="icon-[lucide--flask-conical] mr-2" />
 连接测试
 </Button>
 <Button:disabled="saving || !hasUnsavedChanges"
 class="group relative overflow-hidden"
 @click="saveConfig"
 >
 <span class="absolute inset-0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 配置说明 -->
 <div class=" rounded-2xl border border-dashed border-border/50 bg-muted/20">
 <div class="flex items-start gap-3">
 <span class="icon-[lucide--info] text-xl text-muted-foreground flex-shrink-0 mt-0.5" />
 <div class="space-y-3">
 <h3 class="font-medium">
 配置说明
 </h3>
 <ul class="list-disc list-inside space-y-1 text-sm text-muted-foreground">
 <li>项目级配置将覆盖系统级默认设置</li>
 <li>如果删除项目配置，将自动回退到系统默认值</li>
 <li>API Key 将加密存储，确保安全</li>
 </ul>
 <RouterLink
 to="/admin"
 class="inline-flex items-center text-sm text-primary hover:underline mt-2 group"
 >
 前往系统设置配置默认值
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-1 transition-transform" />
 </RouterLink>
 </div>
 </div>
 </div>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目"
 action-label="返回列表"
 gradient="from-orange-500/20 to-amber-500/20"
 @action="router.push('/projects')"
 />
 <!-- 测试对话框 -->
 <ClaudeTestDialog
 v-model:open="testDialogOpen"
 source="project":project-id="Number(projectId)"
 />
 </div>
</template>
