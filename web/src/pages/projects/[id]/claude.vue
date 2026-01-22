<script setup lang="ts">
import type { Model } from '~/api/chat'
import type { ClaudeConfigCreate, ClaudeConfigRead } from '~/api/settings'
import { useHead } from '@vueuse/head'
/**
 * 项目 Claude 配置页面
 * 用于配置项目的 Claude Code 设置
 */
import { computed, onMounted, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
const projectId = computed( => route.params.id as string)
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
const showApiKey = ref(false)
// 跟踪用户是否修改了值
const apiKeyDirty = ref(false)
const baseUrlDirty = ref(false)
async function loadData {
 loading.value = true
 try {
 await projectsStore.fetchProject(projectId.value)
 try {
 claudeConfig.value = await getProjectClaudeConfig(projectId.value)
 if (claudeConfig.value.base_url) {
 baseUrlValue.value = claudeConfig.value.base_url
 }
 else {
 baseUrlValue.value = ''
 }
 apiKeyValue.value = ''
 }
 catch {
 claudeConfig.value = null
 }
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 }
 catch (e) {
 toast.error('加载失败', {
 description: e instanceof Error ? e.message: '无法获取项目详情',
 })
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
// 检查是否有未保存的更改
function hasUnsavedChanges: boolean {
 return apiKeyDirty.value || baseUrlDirty.value
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
 if (!config.api_key && config.base_url === undefined) {
 toast.info('没有需要保存的更改')
 return
 }
 claudeConfig.value = await updateProjectClaudeConfig(projectId.value, config)
 apiKeyValue.value = ''
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 toast.success('配置已保存')
 }
 catch (e) {
 toast.error('保存失败', {
 description: e instanceof Error ? e.message: '未知错误',
 })
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
 apiKeyDirty.value = false
 baseUrlDirty.value = false
 toast.success('配置已删除，将使用系统默认值')
 await loadData
 }
 catch (e) {
 toast.error('删除失败', {
 description: e instanceof Error ? e.message: '未知错误',
 })
 }
 finally {
 saving.value = false
 }
}
// 模型选择和测试相关
const models = ref<Model>
const selectedModel = ref('')
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
 if (models.value.length > 0 && !selectedModel.value && models.value[0]) {
 selectedModel.value = models.value[0].id
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
 <div class=".5 rounded-xl bg-gradient-to-br from-orange-500/20 to-amber-500/10 flex items-center justify-center">
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
 <div class="absolute -inset-1 bg-gradient-to-r from-orange-500/10 via-amber-500/10 to-orange-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-orange-500/5 to-amber-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--bot] text-orange-500" />
 项目级配置
 </CardTitle>
 <CardDescription>
 为此项目单独配置 Claude Code，将覆盖系统默认设置
 </CardDescription>
 </CardHeader>
 <CardContent class="space-y-6 pt-6">
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
 <Button:disabled="saving || !hasUnsavedChanges"
 class="group relative overflow-hidden"
 @click="saveConfig"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 <!-- 模型测试区域 -->
 <div v-if="canTest" class="space-y-3 pt-4 border-t border-border/50">
 <div class="flex items-center justify-between">
 <div>
 <Label class="text-base">测试配置</Label>
 <p class="text-sm text-muted-foreground">
 验证 API 配置是否正确
 </p>
 </div>
 <Button
 variant="outline":disabled="loadingModels"
 @click="fetchModels"
 >
 <span
 class="icon-[lucide--refresh-cw] mr-2":class="[
 loadingModels && 'animate-spin',
 ]"
 />
 刷新模型
 </Button>
 </div>
 <div class="flex gap-3">
 <!-- 模型选择 -->
 <div class="flex-1">
 <div v-if="loadingModels" class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 正在获取模型列表...
 </div>
 <Select v-else-if="models.length > 0" v-model="selectedModel">
 <SelectTrigger class="">
 <SelectValue placeholder="选择模型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="model in models":key="model.id":value="model.id"
 >
 {{ model.name || model.id }}
 </SelectItem>
 </SelectContent>
 </Select>
 <Input
 v-else
 v-model="selectedModel"
 placeholder="输入模型名称，如 claude-3-5-sonnet-20241022"
 class=""
 />
 </div>
 <!-- 测试按钮 -->
 <Button:disabled="!selectedModel"
 @click="openTestDialog"
 >
 <span class="icon-[lucide--flask-conical] mr-2" />
 测试
 </Button>
 </div>
 </div>
 </CardContent>
 </Card>
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
 to="/settings"
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
