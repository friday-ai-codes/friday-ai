<script setup lang="ts">
import type { Workflow } from '~/stores/useWorkflowsStore'
import { computed, ref, watch } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Label } from '~/components/ui/label'
import { Switch } from '~/components/ui/switch'
import { Textarea } from '~/components/ui/textarea'
const props = defineProps<{
 workflow: Workflow
}>
const emit = defineEmits<{
 confirm: [inputData: Record<string, any>, debugMode: boolean]
 cancel:
 closed:
}>
// 输入数据
const inputJson = ref('')
const parseError = ref('')
const validationErrors = ref<string>
const submitting = ref(false)
const debugMode = ref(false)
// 字段定义
interface FieldDefinition {
 path: string
 name: string
 required: boolean
 description?: string
}
// 飞书事件必填字段（支持原始 Webhook 格式和简化格式）
const feishuRequiredFields: FieldDefinition = [
 { path: 'id', name: '工作项 ID', required: true, description: '飞书工作项唯一标识' },
 { path: 'project_key', name: '项目 Key', required: true, description: '飞书项目标识' },
]
// 检测是否为飞书原始 Webhook 格式（带 header/payload 结构）
function isFeishuRawWebhookFormat(data: Record<string, any>): boolean {
 return !!(data.header && data.payload && typeof data.payload === 'object')
}
// 从飞书数据中提取有效载荷（支持原始格式和简化格式）
function extractFeishuPayload(data: Record<string, any>): Record<string, any> {
 if (isFeishuRawWebhookFormat(data)) {
 return data.payload
 }
 return data
}
// 飞书事件可选字段
const feishuOptionalFields: FieldDefinition = [
 { path: 'work_item_type_key', name: '工作项类型', required: false, description: '如 story, task, bug' },
 { path: 'name', name: '工作项名称', required: false },
 { path: 'cur_work_item_status.state_key', name: '当前状态', required: false },
]
// Webhook 必填字段
const webhookRequiredFields: FieldDefinition = [
 { path: 'event_type', name: '事件类型', required: true, description: '触发事件的类型标识' },
]
// 检测工作流中是否有特殊触发器节点
const triggerNodeType = computed( => {
 if (!props.workflow?.nodes)
 return null
 for (const node of props.workflow.nodes) {
 if (node.node_type === 'feishu_event_trigger')
 return 'feishu'
 if (node.node_type === 'webhook_trigger')
 return 'webhook'
 }
 return null
})
// 是否需要输入数据
const requiresInput = computed( => triggerNodeType.value !== null)
// 当前类型的必填字段
const requiredFields = computed( => {
 switch (triggerNodeType.value) {
 case 'feishu':
 return feishuRequiredFields
 case 'webhook':
 return webhookRequiredFields
 default:
 return
 }
})
// 当前类型的可选字段
const optionalFields = computed( => {
 switch (triggerNodeType.value) {
 case 'feishu':
 return feishuOptionalFields
 default:
 return
 }
})
// 触发器类型配置
const triggerConfig = computed( => {
 switch (triggerNodeType.value) {
 case 'feishu':
 return {
 title: '飞书事件数据',
 description: '请粘贴飞书 Webhook 事件的原始 JSON 数据',
 placeholder: `{
 "id": "12345678",
 "project_key": "your_project_key",
 "work_item_type_key": "story",
 "name": "工作项标题",
 "cur_work_item_status": {
 "state_key": "in_progress",
 "name": "进行中"
 }
}`,
 icon: 'icon-[lucide--message-square]',
 iconColor: 'text-primary',
 bgGradient: 'from-primary/20 to-primary/10',
 }
 case 'webhook':
 return {
 title: 'Webhook 数据',
 description: '请粘贴 Webhook 请求的 JSON 数据',
 placeholder: `{
 "event_type": "your_event_type",
 "data": {
 ...
 }
}`,
 icon: 'icon-[lucide--webhook]',
 iconColor: 'text-primary',
 bgGradient: 'from-primary/20 to-primary/10',
 }
 default:
 return {
 title: '输入数据',
 description: '请输入工作流执行所需的数据',
 placeholder: '{}',
 icon: 'icon-[lucide--play]',
 iconColor: 'text-primary',
 bgGradient: 'from-primary/20 to-primary/10',
 }
 }
})
// 获取嵌套路径的值
function getNestedValue(obj: Record<string, any>, path: string): any {
 const keys = path.split('.')
 let current = obj
 for (const key of keys) {
 if (current == null || typeof current !== 'object')
 return undefined
 current = current[key]
 }
 return current
}
// 验证 JSON 格式和结构
function validateJson: boolean {
 parseError.value = ''
 validationErrors.value =
 if (!inputJson.value.trim) {
 parseError.value = '请输入触发数据'
 return false
 }
 let data: Record<string, any>
 try {
 data = JSON.parse(inputJson.value)
 }
 catch {
 parseError.value = 'JSON 格式不正确，请检查语法'
 return false
 }
 // 对于飞书触发器，支持原始 Webhook 格式（自动从 payload 中提取）
 const dataToValidate = triggerNodeType.value === 'feishu'
 ? extractFeishuPayload(data): data
 // 验证必填字段
 const errors: string =
 for (const field of requiredFields.value) {
 const value = getNestedValue(dataToValidate, field.path)
 if (value === undefined || value === null || value === '') {
 errors.push(`缺少必填字段: ${field.name} (${field.path})`)
 }
 }
 if (errors.length > 0) {
 validationErrors.value = errors
 return false
 }
 return true
}
// 提交
async function handleSubmit {
 if (requiresInput.value && !validateJson)
 return
 submitting.value = true
 try {
 let inputData: Record<string, any> = {}
 if (requiresInput.value) {
 const rawData = JSON.parse(inputJson.value)
 // 对于飞书触发器，自动从原始 Webhook 格式中提取 payload
 inputData = triggerNodeType.value === 'feishu'
 ? extractFeishuPayload(rawData): rawData
 }
 emit('confirm', inputData, debugMode.value)
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('cancel')
}
// 重置表单
watch( => props.workflow, => {
 inputJson.value = ''
 parseError.value = ''
 validationErrors.value =
 debugMode.value = false
})
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br":class="triggerConfig.bgGradient">
 <span:class="[triggerConfig.icon, triggerConfig.iconColor]" class="text-xl" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 执行工作流
 </h3>
 <p class="text-sm text-muted-foreground">
 {{ workflow.name }}
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
 <form class="px-6 py-5 space-y-5 overflow-y-auto" @submit.prevent="handleSubmit">
 <!-- 需要输入数据时显示 -->
 <template v-if="requiresInput">
 <!-- 字段说明 -->
 <div class="space-y-3">
 <div class="flex items-center gap-2 text-sm font-medium text-foreground">
 <span class="icon-[lucide--list-checks] text-muted-foreground" />
 数据结构要求
 </div>
 <!-- 必填字段 -->
 <div class="rounded-lg border border-border/50 bg-muted/30 space-y-2">
 <div class="flex items-center gap-2 text-xs font-medium text-foreground">
 <span class="icon-[lucide--asterisk] text-destructive" />
 必填字段
 </div>
 <div class="grid gap-1.5">
 <div
 v-for="field in requiredFields":key="field.path"
 class="flex items-center gap-2 text-sm"
 >
 <Badge variant="outline" class="font-mono text-xs shrink-0">
 {{ field.path }}
 </Badge>
 <span class="text-muted-foreground">{{ field.name }}</span>
 <span v-if="field.description" class="text-xs text-muted-foreground">
 - {{ field.description }}
 </span>
 </div>
 </div>
 </div>
 <!-- 可选字段 -->
 <div v-if="optionalFields.length > 0" class="rounded-lg border border-border/50 bg-muted/20 space-y-2">
 <div class="flex items-center gap-2 text-xs font-medium text-muted-foreground">
 <span class="icon-[lucide--circle-dashed]" />
 可选字段
 </div>
 <div class="grid gap-1.5">
 <div
 v-for="field in optionalFields":key="field.path"
 class="flex items-center gap-2 text-sm"
 >
 <Badge variant="secondary" class="font-mono text-xs shrink-0">
 {{ field.path }}
 </Badge>
 <span class="text-muted-foreground">{{ field.name }}</span>
 <span v-if="field.description" class="text-xs text-muted-foreground">
 - {{ field.description }}
 </span>
 </div>
 </div>
 </div>
 </div>
 <!-- 输入区域 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-2 text-foreground">
 <span:class="[triggerConfig.icon, triggerConfig.iconColor]" />
 {{ triggerConfig.title }}
 <span class="text-destructive">*</span>
 </Label>
 <p class="text-sm text-muted-foreground">
 {{ triggerConfig.description }}
 </p>
 <Textarea
 v-model="inputJson":placeholder="triggerConfig.placeholder"
 rows="12"
 class="font-mono text-sm resize-none":class="{ 'border-destructive': parseError || validationErrors.length > 0 }"
 />
 <!-- JSON 语法错误 -->
 <p v-if="parseError" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ parseError }}
 </p>
 <!-- 结构验证错误 -->
 <div v-if="validationErrors.length > 0" class="rounded-lg border border-destructive/50 bg-destructive/10 space-y-1">
 <div class="flex items-center gap-2 text-sm font-medium text-destructive">
 <span class="icon-[lucide--alert-triangle]" />
 数据校验失败
 </div>
 <ul class="text-sm text-destructive/90 list-disc list-inside space-y-0.5">
 <li v-for="(error, index) in validationErrors":key="index">
 {{ error }}
 </li>
 </ul>
 </div>
 </div>
 </template>
 <!-- 无需输入数据时显示 -->
 <template v-else>
 <div class="flex flex-col items-center py-6 text-center">
 <div class=" rounded-2xl bg-primary/10 mb-4">
 <span class="icon-[lucide--play-circle] text-4xl text-emerald-500" />
 </div>
 <p class="text-muted-foreground">
 确定要执行此工作流吗？
 </p>
 </div>
 </template>
 <!-- Footer -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <!-- 调试模式开关 -->
 <div class="flex items-center gap-2 mr-auto">
 <Switch:checked="debugMode"
 @update:checked="debugMode = $event"
 />
 <label class="text-sm text-muted-foreground cursor-pointer select-none flex items-center gap-1" @click="debugMode = !debugMode">
 <span class="icon-[lucide--bug] w-3.5 .5" />
 调试模式
 </label>
 </div>
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else-if="debugMode" class="icon-[lucide--bug] mr-2" />
 <span v-else class="icon-[lucide--play] mr-2" />
 {{ debugMode ? '开始调试': '执行' }}
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
