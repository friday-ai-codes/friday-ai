<script setup lang="ts">
import { VueFinalModal } from 'vue-final-modal'
import { get, post, put } from '~/api/client'
import { Button } from '~/components/ui/button'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
const props = defineProps<{
 projectId: string
}>
const emit = defineEmits<{
 confirm: [project: any]
 cancel:
 closed:
}>
const projectsStore = useProjectsStore
const { handleError } = useErrorHandler
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: '',
 description: '',
 feishu_project_key: '',
})
// 飞书 IM 配置
const feishuIMConfig = reactive({
 app_id: '',
 app_secret: '',
 has_app_secret: false,
 is_configured: false,
})
// 测试配置
const testConfig = reactive({
 user_id: '',
 message: '这是一条测试消息，来自 Friday AI Agent 配置测试。',
})
// 表单验证
const errors = reactive({
 name: '',
})
function validate: boolean {
 errors.name = ''
 if (!form.name.trim) {
 errors.name = '请输入项目名称'
 }
 return !errors.name
}
// 加载状态
const loading = ref(false)
const submitting = ref(false)
const feishuIMOpen = ref(false)
const savingFeishuIM = ref(false)
const testingFeishuIM = ref(false)
const testResult = ref<{ success: boolean, message: string } | null>(null)
// 获取项目详情
async function fetchProjectData {
 loading.value = true
 try {
 const project = await projectsStore.fetchProject(props.projectId)
 if (project) {
 form.name = project.name
 form.description = project.description || ''
 form.feishu_project_key = project.feishu_project_key || ''
 }
 // 获取飞书 IM 配置
 await fetchFeishuIMConfig
 }
 catch (e: unknown) {
 handleError(e, '加载项目详情')
 emit('cancel')
 }
 finally {
 loading.value = false
 }
}
async function fetchFeishuIMConfig {
 try {
 const config = await get<{
 app_id: string | null
 has_app_secret: boolean
 is_configured: boolean
 }>(`/projects/${props.projectId}/feishu-im-config/`)
 feishuIMConfig.app_id = config.app_id || ''
 feishuIMConfig.has_app_secret = config.has_app_secret
 feishuIMConfig.is_configured = config.is_configured
 }
 catch {
 // intentionally ignored
 }
}
onMounted( => {
 fetchProjectData
})
// 提交表单
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 const project = await projectsStore.updateProject(props.projectId, {
 name: form.name,
 description: form.description || undefined,
 feishu_project_key: form.feishu_project_key || null,
 })
 success('更新成功', '项目已更新')
 emit('confirm', project)
 }
 catch (e: unknown) {
 handleError(e, '更新项目')
 }
 finally {
 submitting.value = false
 }
}
// 保存飞书 IM 配置
async function saveFeishuIMConfig {
 if (!feishuIMConfig.app_id.trim) {
 showError('验证失败', '请输入 App ID')
 return
 }
 if (!feishuIMConfig.app_secret.trim && !feishuIMConfig.has_app_secret) {
 showError('验证失败', '请输入 App Secret')
 return
 }
 savingFeishuIM.value = true
 try {
 const payload: Record<string, string> = {
 app_id: feishuIMConfig.app_id,
 }
 // 只有输入了新密钥才更新
 if (feishuIMConfig.app_secret.trim) {
 payload.app_secret = feishuIMConfig.app_secret
 }
 await put(`/projects/${props.projectId}/feishu-im-config/`, payload)
 success('保存成功', '飞书 IM 配置已更新')
 feishuIMConfig.has_app_secret = true
 feishuIMConfig.is_configured = true
 feishuIMConfig.app_secret = '' // 清空密钥输入
 }
 catch (e: unknown) {
 handleError(e, '保存飞书 IM 配置')
 }
 finally {
 savingFeishuIM.value = false
 }
}
// 测试飞书 IM 配置
async function testFeishuIMConfig {
 if (!testConfig.user_id.trim) {
 showError('验证失败', '请输入用户 ID')
 return
 }
 testingFeishuIM.value = true
 testResult.value = null
 try {
 const payload: Record<string, string> = {
 user_id: testConfig.user_id,
 message: testConfig.message,
 }
 // 如果输入了临时配置，一并发送用于测试
 if (feishuIMConfig.app_id.trim) {
 payload.app_id = feishuIMConfig.app_id
 }
 if (feishuIMConfig.app_secret.trim) {
 payload.app_secret = feishuIMConfig.app_secret
 }
 const result = await post<{ success: boolean, message: string }>(
 `/projects/${props.projectId}/feishu-im-config/test/`,
 payload,
 )
 testResult.value = result
 if (result.success) {
 success('测试成功', '消息已发送，请检查飞书')
 }
 else {
 showError('测试失败', result.message)
 }
 }
 catch (e: unknown) {
 testResult.value = { success: false, message: e instanceof Error ? e.message: '测试失败' }
 handleError(e, '测试飞书 IM')
 }
 finally {
 testingFeishuIM.value = false
 }
}
function handleCancel {
 emit('cancel')
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4 max-h-[90vh] overflow-hidden"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10">
 <span class="icon-[lucide--pencil] text-xl text-primary" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 编辑项目
 </h3>
 <p class="text-sm text-muted-foreground">
 修改项目基本信息和配置
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
 <div v-if="loading" class=" flex justify-center items-center">
 <span class="icon-[lucide--loader-circle] text-3xl animate-spin text-muted-foreground" />
 </div>
 <form v-else class="px-6 py-5 space-y-5 overflow-y-auto" @submit.prevent="handleSubmit">
 <!-- 项目名称 -->
 <div class="space-y-2">
 <Label for="name" class="flex items-center gap-1 text-foreground">
 项目名称
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：智课项目"
 class="":class="{ 'border-destructive': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.name }}
 </p>
 </div>
 <!-- 项目描述 -->
 <div class="space-y-2">
 <Label for="description" class="text-foreground">项目描述</Label>
 <Textarea
 id="description"
 v-model="form.description"
 placeholder="项目的简要描述..."
 rows="3"
 class="resize-none"
 />
 </div>
 <!-- 飞书项目 Key -->
 <div class="space-y-2">
 <Label for="feishu_project_key" class="flex items-center gap-2 text-foreground">
 飞书项目 Key
 <span class="text-xs text-muted-foreground font-normal">(可选)</span>
 </Label>
 <Input
 id="feishu_project_key"
 v-model="form.feishu_project_key"
 placeholder="例如：project_key"
 class=""
 />
 <p class="text-xs text-muted-foreground">
 用于飞书项目管理 API 调用
 </p>
 </div>
 <Separator />
 <!-- 飞书 IM 配置 (Collapsible) -->
 <Collapsible v-model:open="feishuIMOpen">
 <CollapsibleTrigger class="flex items-center justify-between w-full py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors">
 <span class="flex items-center gap-2">
 <span class="icon-[lucide--message-circle] text-base text-primary" />
 飞书 IM 消息配置
 <span
 v-if="feishuIMConfig.is_configured"
 class="px-1.5 py-0.5 text-[10px] rounded bg-emerald-500/20 text-emerald-600"
 >
 已配置
 </span>
 </span>
 <span
 class="icon-[lucide--chevron-down] transition-transform duration-200":class="{ 'rotate-180': feishuIMOpen }"
 />
 </CollapsibleTrigger>
 <CollapsibleContent class="space-y-4 pt-3">
 <div class="rounded-lg bg-primary/5 border border-primary/20 text-xs text-muted-foreground space-y-1">
 <p class="font-medium text-primary">
 配置说明
 </p>
 <p>用于 AI Agent 发送飞书消息（如提问卡片、通知等）。</p>
 <p>需要在飞书开放平台创建<strong>自建应用</strong>并开启消息权限。</p>
 </div>
 <!-- App ID -->
 <div class="space-y-1.5">
 <Label class="text-xs">App ID</Label>
 <Input
 v-model="feishuIMConfig.app_id"
 placeholder="cli_xxxxxxxxxx"
 class=" text-sm font-mono"
 />
 <p class="text-[10px] text-muted-foreground">
 飞书开放平台 → 应用管理 → 凭证与基础信息
 </p>
 </div>
 <!-- App Secret -->
 <div class="space-y-1.5">
 <Label class="text-xs flex items-center gap-2">
 App Secret
 <span
 v-if="feishuIMConfig.has_app_secret"
 class="text-[10px] text-emerald-600"
 >
 (已配置，留空则保持不变)
 </span>
 </Label>
 <Input
 v-model="feishuIMConfig.app_secret"
 type="password":placeholder="feishuIMConfig.has_app_secret ? '••••••••••••••••': '输入 App Secret'"
 class=" text-sm"
 />
 </div>
 <!-- 保存按钮 -->
 <Button
 type="button"
 size="sm":disabled="savingFeishuIM"
 @click="saveFeishuIMConfig"
 >
 <span v-if="savingFeishuIM" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存 IM 配置
 </Button>
 <Separator />
 <!-- 测试发送 -->
 <div class="space-y-3">
 <p class="text-xs font-medium text-foreground flex items-center gap-1.5">
 <span class="icon-[lucide--flask-conical] text-primary" />
 测试消息发送
 </p>
 <div class="space-y-1.5">
 <Label class="text-xs">用户 ID (open_id)</Label>
 <Input
 v-model="testConfig.user_id"
 placeholder="ou_xxxxxxxxxx"
 class=" text-sm font-mono"
 />
 <p class="text-[10px] text-muted-foreground">
 获取方式：飞书管理后台 → 成员管理 → 点击成员 → 复制 Open ID
 </p>
 </div>
 <div class="space-y-1.5">
 <Label class="text-xs">测试消息</Label>
 <Textarea
 v-model="testConfig.message"
 rows="2"
 class="text-sm resize-none"
 />
 </div>
 <Button
 type="button"
 variant="outline"
 size="sm":disabled="testingFeishuIM"
 @click="testFeishuIMConfig"
 >
 <span v-if="testingFeishuIM" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--send] mr-2" />
 发送测试消息
 </Button>
 <!-- 测试结果 -->
 <div
 v-if="testResult"
 class="rounded-lg .5 text-xs":class="testResult.success ? 'bg-emerald-500/10 text-emerald-600': 'bg-destructive/10 text-destructive'"
 >
 <span:class="testResult.success ? 'icon-[lucide--check-circle]': 'icon-[lucide--x-circle]'" class="mr-1.5" />
 {{ testResult.message }}
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
 <!-- Footer -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存修改
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
