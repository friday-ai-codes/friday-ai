<script setup lang="ts">
import type { ClaudeConfigCreate, ClaudeConfigRead } from '~/api/settings'
import { useHead } from '@vueuse/head'
/**
 * 项目 Claude 配置页面
 * 用于配置项目的 Claude Code 设置
 */
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import {
 deleteProjectClaudeConfig,
 getProjectClaudeConfig,
 updateProjectClaudeConfig,
} from '~/api/settings'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
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
 // Base URL 直接使用返回的值
 if (claudeConfig.value.base_url) {
 baseUrlValue.value = claudeConfig.value.base_url
 }
 else {
 baseUrlValue.value = ''
 }
 // API Key 不显示，只显示是否已配置
 apiKeyValue.value = ''
 }
 catch {
 // 配置不存在是正常情况
 claudeConfig.value = null
 }
 // 重置脏标记
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
 // 只在用户实际修改过才保存
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
 apiKeyValue.value = '' // 清空密钥输入
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
 await loadData // 重新加载以获取回退的配置
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
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-6">
 <!-- 返回按钮 -->
 <RouterLink:to="`/projects/${projectId}`"
 class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
 >
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回项目详情
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="2" />
 <template v-else-if="project">
 <div>
 <h1 class="text-2xl font-bold">
 Claude 配置
 </h1>
 <p class="text-muted-foreground">
 配置 {{ project.name }} 的 Claude Code 设置
 </p>
 </div>
 <!-- 配置表单 -->
 <Card>
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--bot]" />
 项目级配置
 </CardTitle>
 <CardDescription>
 为此项目单独配置 Claude Code，将覆盖系统默认设置
 </CardDescription>
 </CardHeader>
 <CardContent class="space-y-6">
 <!-- API Key -->
 <div class="space-y-2">
 <Label for="api-key">Anthropic API Key</Label>
 <p class="text-sm text-muted-foreground">
 为此项目单独配置的 API 密钥，将覆盖系统默认值
 </p>
 <div class="flex gap-2">
 <div class="relative flex-1">
 <Input
 id="api-key"
 v-model="apiKeyValue":type="showApiKey ? 'text': 'password'"
 placeholder="sk-ant-..."
 class="pr-10"
 @input="onApiKeyInput"
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
 @click="showApiKey = !showApiKey"
 >
 <span:class="showApiKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 </div>
 <p v-if="claudeConfig?.has_api_key" class="text-sm text-green-600 flex items-center gap-1">
 <span class="icon-[lucide--check-circle]" />
 已配置 API Key
 <Badge v-if="sourceLabel":variant="sourceLabel.variant" class="ml-2">
 {{ sourceLabel.text }}
 </Badge>
 </p>
 </div>
 <!-- Base URL -->
 <div class="space-y-2">
 <Label for="base-url">Anthropic Base URL</Label>
 <p class="text-sm text-muted-foreground">
 API 基础地址，用于代理或自定义端点
 </p>
 <Input
 id="base-url"
 v-model="baseUrlValue"
 type="url"
 placeholder="https://api.anthropic.com"
 @input="onBaseUrlInput"
 />
 <p v-if="claudeConfig?.base_url" class="text-sm text-muted-foreground">
 当前值: {{ claudeConfig.base_url }}
 </p>
 </div>
 <!-- 操作按钮 -->
 <div class="flex justify-between items-center pt-4 border-t">
 <Button
 v-if="claudeConfig?.source === 'project'"
 variant="destructive":disabled="saving"
 @click="removeConfig"
 >
 删除项目配置
 </Button>
 <div v-else />
 <Button:disabled="saving || !hasUnsavedChanges" @click="saveConfig">
 <span v-if="saving" class="icon-[lucide--loader-2] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存设置
 </Button>
 </div>
 </CardContent>
 </Card>
 <!-- 配置说明 -->
 <Card class="border-dashed">
 <CardHeader>
 <CardTitle class="text-base flex items-center gap-2">
 <span class="icon-[lucide--info]" />
 配置说明
 </CardTitle>
 </CardHeader>
 <CardContent class="text-sm text-muted-foreground space-y-2">
 <ul class="list-disc list-inside space-y-1">
 <li>项目级配置将覆盖系统级默认设置</li>
 <li>如果删除项目配置，将自动回退到系统默认值</li>
 <li>API Key 将加密存储，确保安全</li>
 <li>如果系统级也未配置，将使用环境变量 ANTHROPIC_API_KEY</li>
 </ul>
 <RouterLink
 to="/settings"
 class="inline-flex items-center text-sm text-primary hover:underline mt-2"
 >
 前往系统设置配置默认值
 <span class="icon-[lucide--arrow-right] ml-1" />
 </RouterLink>
 </CardContent>
 </Card>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目"
 action-label="返回列表"
 @action="router.push('/projects')"
 />
 </div>
</template>
