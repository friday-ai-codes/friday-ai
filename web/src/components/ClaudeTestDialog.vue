<script setup lang="ts">
/**
 * Claude 配置测试对话框组件
 * 用于测试 Claude API 配置是否正确
 */
import type { ChatCompletionResponse, ConfigSource, Model } from '~/api/chat'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { chatCompletion, getModels } from '~/api/chat'
import { Button } from '~/components/ui/button'
import {
 Dialog,
 DialogContent,
 DialogDescription,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from '~/components/ui/dialog'
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
 <Dialog v-model:open="isOpen">
 <DialogContent class="sm:max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
 <DialogHeader>
 <DialogTitle class="flex items-center gap-2">
 <span class="icon-[lucide--flask-conical] text-primary" />
 测试 Claude 配置
 </DialogTitle>
 <DialogDescription>
 发送测试消息验证 API 配置是否正确
 </DialogDescription>
 </DialogHeader>
 <div class="flex-1 overflow-y-auto space-y-4 py-4">
 <!-- 模型选择 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <Label>选择模型</Label>
 <Button
 variant="ghost"
 size="sm":disabled="loadingModels"
 @click="refreshModels"
 >
 <span
 class="icon-[lucide--refresh-cw] mr-1":class="[
 loadingModels && 'animate-spin',
 ]"
 />
 刷新
 </Button>
 </div>
 <div v-if="loadingModels" class="flex items-center gap-2 text-muted-foreground">
 <span class="icon-[lucide--loader-circle] animate-spin" />
 正在获取模型列表...
 </div>
 <Select v-else-if="hasModels" v-model="selectedModel">
 <SelectTrigger>
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
 <Input
 v-model="selectedModel"
 placeholder="输入模型名称，如 claude-3-5-sonnet-20241022"
 />
 <p class="text-xs text-muted-foreground">
 无法获取模型列表，请手动输入模型名称
 </p>
 </div>
 </div>
 <!-- 测试输入 -->
 <div class="space-y-2">
 <Label for="test-prompt">测试内容</Label>
 <Textarea
 id="test-prompt"
 v-model="testPrompt"
 placeholder="输入要发送给 AI 的测试消息..."
 class="min- resize-none"
 />
 </div>
 <!-- 错误提示 -->
 <div
 v-if="error"
 class=" rounded-lg bg-destructive/10 border border-destructive/20 text-destructive"
 >
 <div class="flex items-start gap-2">
 <span class="icon-[lucide--alert-circle] flex-shrink-0 mt-0.5" />
 <div>
 <p class="font-medium">
 测试失败
 </p>
 <p class="text-sm mt-1">
 {{ error }}
 </p>
 </div>
 </div>
 </div>
 <!-- 结果展示 -->
 <div v-if="result" class="space-y-2">
 <Label>测试结果</Label>
 <div class=" rounded-lg bg-muted/50 border border-border/50">
 <div class="prose prose-sm dark:prose-invert max-w-none">
 <p class="whitespace-pre-wrap">
 {{ result.content }}
 </p>
 </div>
 <div v-if="result.usage" class="mt-3 pt-3 border-t border-border/50 text-xs text-muted-foreground flex items-center gap-4">
 <span>模型: {{ result.model }}</span>
 <span>Tokens: {{ result.usage.total_tokens }}</span>
 </div>
 </div>
 </div>
 </div>
 <DialogFooter class="gap-2 sm:gap-0">
 <Button variant="outline" @click="close">
 关闭
 </Button>
 <Button:disabled="loading || !selectedModel"
 @click="sendTest"
 >
 <span
 v-if="loading"
 class="icon-[lucide--loader-circle] animate-spin mr-2"
 />
 <span v-else class="icon-[lucide--send] mr-2" />
 发送测试
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
</template>
