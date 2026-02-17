<script setup lang="ts">
import { VueFinalModal } from 'vue-final-modal'
import { getProjectClaudeConfig, updateProjectClaudeConfig } from '~/api/settings'
import ClaudeTestDialog from '~/components/ClaudeTestDialog.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
const props = defineProps<{
 projectId: string
}>
const emit = defineEmits<{
 confirm:
 cancel:
 closed:
}>
const { success, error: showError } = useToast
// 状态
const loading = ref(false)
const submitting = ref(false)
const testDialogOpen = ref(false)
const showApiKey = ref(false)
// 表单数据
const form = reactive({
 api_key: '',
 base_url: '',
 default_model: '',
})
// 加载配置
async function loadData {
 loading.value = true
 try {
 const config = await getProjectClaudeConfig(props.projectId)
 if (config) {
 form.base_url = config.base_url || ''
 form.default_model = config.default_model || ''
 // API Key is not returned for security, so we leave it empty
 // If user wants to update, they enter a new one
 }
 }
 catch {
 // intentionally ignored
 }
 finally {
 loading.value = false
 }
}
onMounted(loadData)
// 提交表单
async function handleSubmit {
 submitting.value = true
 try {
 await updateProjectClaudeConfig(props.projectId, {
 api_key: form.api_key || undefined,
 base_url: form.base_url || undefined,
 default_model: form.default_model || undefined,
 })
 success('配置已保存')
 emit('confirm')
 }
 catch (e) {
 showError('保存失败', e instanceof Error ? e.message: '无法保存配置')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('cancel')
}
function openTestDialog {
 testDialogOpen.value = true
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/10">
 <span class="icon-[lucide--bot] text-xl text-emerald-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 Claude 配置
 </h3>
 <p class="text-sm text-muted-foreground">
 配置项目的 Claude API 连接信息
 </p>
 </div>
 </div>
 <button
 type="button"
 class=" rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="handleCancel"
 >
 <span class="icon-[lucide--x] text-lg" />
 </button>
 </div>
 <!-- Body -->
 <form class="px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
 <!-- API Key -->
 <div class="space-y-2">
 <Label for="api-key" class="text-foreground">Anthropic API Key</Label>
 <div class="relative">
 <Input
 id="api-key"
 v-model="form.api_key":type="showApiKey ? 'text': 'password'"
 placeholder="sk-ant-..."
 class="pr-10 "
 />
 <button
 type="button"
 class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
 @click="showApiKey = !showApiKey"
 >
 <span:class="showApiKey ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'" />
 </button>
 </div>
 <p class="text-xs text-muted-foreground">
 留空则保持原有配置不变
 </p>
 </div>
 <!-- Base URL -->
 <div class="space-y-2">
 <Label for="base-url" class="text-foreground">Anthropic Base URL</Label>
 <Input
 id="base-url"
 v-model="form.base_url"
 placeholder="https://api.anthropic.com"
 class=""
 />
 <p class="text-xs text-muted-foreground">
 可选，用于自定义 API 代理地址
 </p>
 </div>
 <!-- 默认模型 -->
 <div class="space-y-2">
 <Label for="default-model" class="text-foreground">默认模型</Label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--cpu] text-muted-foreground" />
 <Input
 id="default-model"
 v-model="form.default_model"
 placeholder="如 claude-sonnet-4-20250514"
 class="pl-10 "
 />
 </div>
 <p class="text-xs text-muted-foreground">
 用于所有未指定模型的调用，留空则使用系统默认模型
 </p>
 </div>
 <!-- Footer -->
 <div class="flex justify-between items-center pt-4 border-t border-border/50">
 <Button
 type="button"
 variant="outline"
 class="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 border-emerald-200"
 @click="openTestDialog"
 >
 <span class="icon-[lucide--flask-conical] mr-2" />
 测试连接
 </Button>
 <div class="flex gap-3">
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting" class="bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white border-0">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存配置
 </Button>
 </div>
 </div>
 </form>
 <!-- 测试对话框 -->
 <ClaudeTestDialog
 v-model:open="testDialogOpen"
 source="project":project-id="Number(projectId)":api-key="form.api_key || undefined":base-url="form.base_url || undefined"
 />
 </VueFinalModal>
</template>
