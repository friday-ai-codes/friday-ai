<script setup lang="ts">
/**
 * Claude 配置测试对话框组件
 * 用于测试 Claude API 配置是否正确
 */
import type { ChatCompletionResponse, ConfigSource, Model } from '~/api/chat'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { chatCompletion, getModels } from '~/api/chat'
import BaseModal from '~/components/modal/BaseModal.vue'
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
const props = defineProps<{
 /** 是否显示对话框 */
 open: boolean
 /** 配置来源 */
 source: ConfigSource
 /** 项目 ID（当 source=project 时） */
 projectId?: number
 /** 临时 API Key（用于测试未保存的配置） */
 apiKey?: string
 /** 临时 Base URL（用于测试未保存的配置） */
 baseUrl?: string
}>
const emit = defineEmits<{
 'update:open': [value: boolean]
}>
// 状态
const loading = ref(false)
const loadingModels = ref(false)
const models = ref<Model>
const selectedModel = ref('')
const testPrompt = ref('你基于什么模型？')
const result = ref<ChatCompletionResponse | null>(null)
const error = ref('')
// 计算属性
const isOpen = computed({
 get: => props.open,
 set: value => emit('update:open', value),
})
const hasModels = computed( => models.value.length > 0)
// 测试状态
const testStatus = computed( => {
 if (loading.value)
 return 'loading'
 if (error.value)
 return 'error'
 if (result.value)
 return 'success'
 return 'idle'
})
// 监听对话框打开
watch( => props.open, async (open) => {
 if (open) {
 // 重置状态
 result.value = null
 error.value = ''
 testPrompt.value = '你基于什么模型？'
 // 加载模型列表
 if (models.value.length === 0) {
 await fetchModels
 }
 }
})
// 获取模型列表
async function fetchModels {
 loadingModels.value = true
 error.value = ''
 try {
 const response = await getModels({
 source: props.source,
 project_id: props.projectId,
 api_key: props.apiKey,
 base_url: props.baseUrl,
 })
 models.value = response.models
 // 默认选中第一个模型
 if (models.value.length > 0 && !selectedModel.value && models.value[0]) {
 selectedModel.value = models.value[0].id
 }
 }
 catch (e) {
 console.error('Failed to fetch models:', e)
 error.value = e instanceof Error ? e.message: '获取模型列表失败'
 }
 finally {
 loadingModels.value = false
 }
}
// 发送测试
async function sendTest {
 if (!selectedModel.value) {
 toast.error('请选择模型')
 return
 }
 if (!testPrompt.value.trim) {
 toast.error('请输入测试内容')
 return
 }
 loading.value = true
 result.value = null
 error.value = ''
 try {
 result.value = await chatCompletion({
 model: selectedModel.value,
 messages: [{ role: 'user', content: testPrompt.value.trim }],
 source: props.source,
 project_id: props.projectId,
 api_key: props.apiKey,
 base_url: props.baseUrl,
 })
 }
 catch (e) {
 console.error('Test failed:', e)
 error.value = e instanceof Error ? e.message: '测试失败'
 }
 finally {
 loading.value = false
 }
}
// 关闭对话框
function close {
 isOpen.value = false
}
// 重新获取模型
function refreshModels {
 models.value =
 selectedModel.value = ''
 fetchModels
}
</script>
<template>
 <BaseModal
 v-model="isOpen"
 size="lg":show-close="false":content-padding="false"
 >
 <div class="flex flex-col h-[85vh] sm:h-auto sm:max-h-[85vh]">
 <!-- 装饰性顶部条纹 -->
 <div class=" bg-gradient-to-r from-emerald-500 via-cyan-500 to-blue-500 shrink-0" />
 <!-- 头部 -->
 <div class="px-6 pt-5 pb-4 border-b border-border/50 bg-gradient-to-r from-emerald-500/5 to-cyan-500/5 shrink-0">
 <div class="flex items-center gap-3">
 <div class="relative">
 <div class="absolute inset-0 bg-gradient-to-br from-emerald-500 to-cyan-500 rounded-xl blur-sm opacity-40" />
 <div class="relative .5 rounded-xl bg-gradient-to-br from-emerald-500 to-cyan-600 flex items-center justify-center">
 <span class="icon-[lucide--flask-conical] text-xl text-white" />
 </div>
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 连接测试
 </h2>
 <p class="text-sm text-muted-foreground">
 发送测试消息验证 API 配置是否正确
 </p>
 </div>
 </div>
 </div>
 <!-- 内容区域 -->
 <div class="flex-1 overflow-y-auto px-6 py-5 space-y-5">
 <!-- 模型选择 -->
 <div class="space-y-3">
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2 text-sm">
 <span class="icon-[lucide--cpu] text-muted-foreground" />
 <Label class="font-medium">选择模型</Label>
 </div>
 <button:disabled="loadingModels"
 class="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground bg-muted/50 hover:bg-muted rounded-lg transition-all duration-200 disabled:opacity-50 cursor-pointer"
 @click="refreshModels"
 >
 <span
 class="icon-[lucide--refresh-cw]":class="loadingModels && 'animate-spin'"
 />
 刷新
 </button>
 </div>
 <!-- 加载状态 -->
 <div v-if="loadingModels" class="flex items-center justify-center gap-3 py-6 bg-muted/30 rounded-xl border border-dashed border-border/50">
 <div class="relative">
 <div class="absolute inset-0 bg-primary/20 rounded-full blur animate-pulse" />
 <span class="relative icon-[lucide--loader-circle] text-xl text-primary animate-spin" />
 </div>
 <span class="text-sm text-muted-foreground">正在获取模型列表...</span>
 </div>
 <Select v-else-if="hasModels" v-model="selectedModel">
 <SelectTrigger class=" bg-muted/30 border-border/50">
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
 <div v-else class="space-y-2">
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--type] text-muted-foreground" />
 <Input
 v-model="selectedModel"
 placeholder="输入模型名称，如 claude-sonnet-4-20250514"
 class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <p class="text-xs text-muted-foreground">
 无法获取模型列表，请手动输入模型名称
 </p>
 </div>
 </div>
 <!-- 测试输入 -->
 <div class="space-y-3">
 <div class="flex items-center gap-2 text-sm">
 <span class="icon-[lucide--message-square] text-muted-foreground" />
 <Label for="test-prompt" class="font-medium">测试消息</Label>
 </div>
 <Textarea
 id="test-prompt"
 v-model="testPrompt"
 placeholder="输入要发送给 AI 的测试消息..."
 class="min-h-[100px] resize-none bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <!-- 结果区域 -->
 <div
 v-if="testStatus !== 'idle'"
 class="rounded-xl border overflow-hidden":class="{
 'border-border/50 bg-muted/20': testStatus === 'loading',
 'border-destructive/30 bg-destructive/5': testStatus === 'error',
 'border-emerald-500/30 bg-gradient-to-br from-emerald-50/50 to-cyan-50/30 dark:from-emerald-950/20 dark:to-cyan-950/10': testStatus === 'success',
 }"
 >
 <!-- 加载状态 -->
 <div v-if="testStatus === 'loading'" class="flex items-center justify-center gap-3 py-10">
 <div class="relative">
 <div class="absolute inset-0 bg-gradient-to-br from-emerald-500/30 to-cyan-500/30 rounded-full blur animate-pulse" />
 <span class="relative icon-[lucide--loader-circle] text-2xl text-emerald-500 animate-spin" />
 </div>
 <span class="text-sm text-muted-foreground">正在测试连接...</span>
 </div>
 <!-- 错误状态 -->
 <div v-else-if="testStatus === 'error'" class="">
 <div class="flex items-start gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-destructive/20 to-destructive/10 flex items-center justify-center flex-shrink-0">
 <span class="icon-[lucide--x] text-lg text-destructive" />
 </div>
 <div class="flex-1 min-w-0">
 <p class="font-semibold text-destructive">
 连接失败
 </p>
 <p class="text-sm text-destructive/80 mt-1 break-words">
 {{ error }}
 </p>
 </div>
 </div>
 </div>
 <!-- 成功状态 -->
 <div v-else-if="testStatus === 'success' && result" class="divide-y divide-emerald-500/20">
 <!-- 成功标识 -->
 <div class="flex items-center gap-3 px-4 py-3 bg-gradient-to-r from-emerald-500/10 to-cyan-500/5">
 <div class=".5 rounded-full bg-gradient-to-br from-emerald-500 to-cyan-500 shadow-lg shadow-emerald-500/25">
 <span class="icon-[lucide--check] text-sm text-white" />
 </div>
 <span class="font-semibold bg-gradient-to-r from-emerald-600 to-cyan-600 bg-clip-text text-transparent">连接成功</span>
 </div>
 <!-- 响应内容 -->
 <div class="">
 <div class="prose prose-sm dark:prose-invert max-w-none">
 <p class="whitespace-pre-wrap leading-relaxed">
 {{ result.content }}
 </p>
 </div>
 </div>
 <!-- 元信息 -->
 <div v-if="result.usage" class="px-4 py-3 bg-muted/30 flex items-center gap-4 text-xs text-muted-foreground">
 <span class="inline-flex items-center gap-1.5">
 <span class="icon-[lucide--cpu]" />
 {{ result.model }}
 </span>
 <span class="inline-flex items-center gap-1.5">
 <span class="icon-[lucide--hash]" />
 {{ result.usage.total_tokens }} tokens
 </span>
 </div>
 </div>
 </div>
 </div>
 <!-- 底部操作栏 -->
 <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-border/50 shrink-0">
 <Button variant="outline" class="hover:border-primary/50" @click="close">
 关闭
 </Button>
 <Button:disabled="loading || !selectedModel"
 class="group relative overflow-hidden bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white shadow-lg shadow-emerald-500/25 disabled:opacity-50 disabled:shadow-none"
 @click="sendTest"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span
 v-if="loading"
 class="icon-[lucide--loader-circle] animate-spin mr-2"
 />
 <span v-else class="icon-[lucide--send] mr-2 group-hover:translate-x-0.5 transition-transform" />
 发送测试
 </Button>
 </div>
 </div>
 </BaseModal>
</template>
