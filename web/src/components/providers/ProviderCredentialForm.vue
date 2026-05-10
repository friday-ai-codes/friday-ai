<script setup lang="ts">
import type {
 JsonSchemaProperty,
 ProviderCredentialCreatePayload,
 ProviderCredentialDto,
 ProviderCredentialUpdatePayload,
 ProviderType,
} from '~/types/providerCredential'
/**
 * Provider 凭证 schema-driven 动态表单（Phase + CONTEXT ~）
 *
 * 字段源：store.providerTypes[selectedType].credential_schema_json_schema.properties
 *
 * 动态分派规则（work item §I-1）:
 * - format=password 或 writeOnly=true → Input type=password + 眼睛 toggle（仅 edit 模式可切显）
 * - format=uri → Input type=url + 提交前 new URL try/catch 校验
 * - anyOf: [string, null] → optional string input（label 后缀 "(可选)"）
 * - pattern → zod schema regex 校验
 *
 * Typography: 所有 FormLabel 显式 class="font-normal" 覆盖 shadcn-vue Label 默认 font-medium。
 * dirty state: meta.dirty 变化冒泡 emit('dirty') 供父容器弹"未保存修改"AlertDialog（work item §I-5）。
 */
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { computed, ref, watch } from 'vue'
import * as z from 'zod'
import { Button } from '~/components/ui/button'
import {
 FormControl,
 FormField,
 FormItem,
 FormLabel,
 FormMessage,
} from '~/components/ui/form'
import { Input } from '~/components/ui/input'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { providerCredentialsApi } from '~/api/providerCredentials'
import { useToast } from '~/composables/useToast'
import { useProviderCredentialStore } from '~/stores/providerCredential'
interface Props {
 initial?: ProviderCredentialDto
 mode: 'create' | 'edit'
 defaultScope?: 'system' | 'project'
 defaultProjectId?: string | null
}
const props = withDefaults(defineProps<Props>, {
 initial: undefined,
 defaultScope: 'system',
 defaultProjectId: null,
})
const emit = defineEmits<{
 (e: 'submit', payload: ProviderCredentialCreatePayload | ProviderCredentialUpdatePayload): void
 (e: 'cancel'): void
 (e: 'dirty', isDirty: boolean): void
}>
const store = useProviderCredentialStore
const toast = useToast
// 模型获取状态
const isFetchingModels = ref(false)
const fetchModelsError = ref<string | null>(null)
const fetchedModels = ref<Array<{ id: string, display_name: string }>>
const showManualModelInput = ref(false)
const manualModelName = ref('')
const selectedDefaultModel = ref('')
// 模型测试状态
const testingModelId = ref<string | null>(null)
const modelTestResults = ref<Record<string, { status: 'ok' | 'error', latency_ms?: number, error?: string }>>({})
// 确保 providerTypes 就位（store 内部去重，重复调用无副作用）
if (store.providerTypes.length === 0) {
 store.fetchProviderTypes.catch( => {
 // 错误由父组件通过 useErrorHandler 承接
 })
}
const selectedType = ref<ProviderType>(props.initial?.provider_type ?? 'anthropic')
const passwordVisible = ref<Record<string, boolean>>({})
const currentMeta = computed( =>
 store.providerTypes.find(p => p.provider_type === selectedType.value),
)
const schemaProperties = computed<Record<string, JsonSchemaProperty>>(
 => (currentMeta.value?.credential_schema_json_schema?.properties ?? {}) as Record<string, JsonSchemaProperty>,
)
const schemaRequired = computed<string>(
 => currentMeta.value?.credential_schema_json_schema?.required ??,
)
function isPasswordField(prop: JsonSchemaProperty): boolean {
 if (prop.format === 'password' || prop.writeOnly)
 return true
 return (prop.anyOf ?? ).some(sub => sub.format === 'password' || sub.writeOnly === true)
}
function isUriField(prop: JsonSchemaProperty): boolean {
 if (prop.format === 'uri')
 return true
 return (prop.anyOf ?? ).some(sub => sub.format === 'uri')
}
function isOptional(prop: JsonSchemaProperty, key: string): boolean {
 if (!schemaRequired.value.includes(key))
 return true
 // anyOf 含 null 类型也视为可选
 return (prop.anyOf ?? ).some(sub => sub.type === 'null')
}
// ==== 动态 zod schema ====
const zodSchema = computed( => {
 const shape: Record<string, z.ZodTypeAny> = {
 provider_type: z.enum(['anthropic', 'openai_responses', 'openai_chat', 'gemini', 'ollama']),
 name: z.string.min(1, '请输入凭证名称').max(100, '名称最长 100 字符'),
 scope: z.enum(['system', 'project']),
 scope_id: z.string.uuid('请选择有效空间').nullable.optional,
 is_active: z.boolean.optional,
 default_model: z.string.min(1, '请输入或选择一个模型'),
 }
 const configShape: Record<string, z.ZodTypeAny> = {}
 for (const [key, prop] of Object.entries(schemaProperties.value)) {
 let fieldSchema: z.ZodTypeAny = z.string
 if (isUriField(prop)) {
 fieldSchema = z.string.refine((v: string) => {
 if (!v)
 return true
 try {
 return Boolean(new URL(v).protocol)
 }
 catch {
 return false
 }
 }, '必须是合法 URL（包含 http:// 或 https://）')
 }
 if (prop.pattern) {
 const pat = new RegExp(prop.pattern)
 fieldSchema = z.string.regex(pat, `必须匹配 ${prop.pattern}`)
 }
 if (isOptional(prop, key))
 fieldSchema = (fieldSchema as z.ZodString).optional.or(z.literal(''))
 else
 fieldSchema = (fieldSchema as z.ZodString).min(1, `请输入${prop.title ?? key}`)
 configShape[key] = fieldSchema
 }
 shape.config = z.object(configShape)
 return z.object(shape)
})
const formSchema = computed( => toTypedSchema(zodSchema.value))
const { handleSubmit, meta, setValues } = useForm({
 validationSchema: formSchema,
 initialValues: {
 provider_type: selectedType.value,
 name: props.initial?.name ?? '',
 scope: props.initial?.scope ?? props.defaultScope,
 scope_id: props.initial?.scope_id ?? props.defaultProjectId,
 is_active: props.initial?.is_active ?? true,
 default_model: props.initial?.default_model ?? '',
 // edit 模式下回显已配置的 base_url / api_key（后端按写权限分级返回）。
 config: { ...(props.initial?.config ?? {}) } as Record<string, unknown>,
 },
})
// 切换 selectedType 时重置 config 字段集
watch(selectedType, (type) => {
 setValues({ provider_type: type, config: {} } as Record<string, unknown>, false)
})
// dirty 冒泡
watch( => meta.value.dirty, (v) => {
 emit('dirty', v)
})
const onSubmit = handleSubmit((v) => {
 const defaultModel = (v.default_model as string)?.trim || selectedDefaultModel.value || ''
 if (props.mode === 'create') {
 const payload: ProviderCredentialCreatePayload = {
 provider_type: v.provider_type as ProviderType,
 name: v.name as string,
 scope: v.scope as 'system' | 'project',
 scope_id: (v.scope_id as string | null | undefined) ?? null,
 config: (v.config as Record<string, unknown>) ?? {},
 is_active: (v.is_active as boolean | undefined) ?? true,
 default_model: defaultModel,
 }
 emit('submit', payload)
 }
 else {
 const configObj = (v.config as Record<string, unknown>) ?? {}
 const payload: ProviderCredentialUpdatePayload = {
 name: v.name as string,
 scope: v.scope as 'system' | 'project',
 scope_id: (v.scope_id as string | null | undefined) ?? null,
 config: Object.keys(configObj).length > 0 ? configObj: null,
 is_active: v.is_active as boolean | undefined,
 }
 if (defaultModel) {
 payload.default_model = defaultModel
 }
 emit('submit', payload)
 }
})
/** 创建凭证成功后自动获取模型列表 */
async function fetchModelsAfterCreate(credentialId: string) {
 isFetchingModels.value = true
 fetchModelsError.value = null
 try {
 const resp = await providerCredentialsApi.refreshModels(credentialId)
 fetchedModels.value = resp.available_models
 if (resp.available_models.length === 0) {
 fetchModelsError.value = '未获取到模型列表，请手动输入一个模型名称'
 showManualModelInput.value = true
 }
 else {
 // 自动选择第一个模型作为 default_model
 selectedDefaultModel.value = resp.available_models[0].id
 toast.success(`成功获取 ${resp.available_models.length} 个模型`)
 }
 }
 catch (e) {
 fetchModelsError.value = e instanceof Error ? e.message: '获取模型列表失败'
 showManualModelInput.value = true
 }
 finally {
 isFetchingModels.value = false
 }
}
/** 手动获取模型列表（用户主动触发） */
async function handleFetchModels {
 if (!props.initial?.id)
 return
 await fetchModelsAfterCreate(props.initial.id)
}
/** 确认手动输入的模型 */
function confirmManualModel {
 if (!manualModelName.value.trim) {
 toast.error('请输入模型名称')
 return
 }
 const modelName = manualModelName.value.trim
 selectedDefaultModel.value = modelName
 setValues({ default_model: modelName } as Record<string, unknown>, false)
 showManualModelInput.value = false
 toast.success(`已设置默认模型: ${modelName}`)
}
/** 测试指定模型的连接 */
async function testModel(modelId: string) {
 if (!props.initial?.id)
 return
 testingModelId.value = modelId
 try {
 const resp = await providerCredentialsApi.testConnection(props.initial.id, modelId)
 modelTestResults.value = {
 ...modelTestResults.value,
 [modelId]: { status: resp.status, latency_ms: resp.latency_ms },
 }
 if (resp.status === 'ok') {
 toast.success(`模型 ${modelId} 连接成功 (${resp.latency_ms}ms)`)
 }
 else {
 toast.error(`模型 ${modelId} 连接失败: ${resp.error ?? '未知错误'}`)
 }
 }
 catch (e) {
 modelTestResults.value = {
 ...modelTestResults.value,
 [modelId]: { status: 'error', error: e instanceof Error ? e.message: '测试失败' },
 }
 toast.error(`模型 ${modelId} 测试失败`)
 }
 finally {
 testingModelId.value = null
 }
}
function togglePassword(key: string) {
 passwordVisible.value[key] = !passwordVisible.value[key]
}
function getPlaceholder(key: string): string {
 const t = selectedType.value
 const placeholders: Record<string, string> = {
 api_key: t === 'anthropic'
 ? 'sk-test-placeholder': t === 'gemini'
 ? 'AIzaSyxxxxxxxxxxxxxxxx': 'sk-xxxxxxxxxxxxxxxx',
 base_url: t === 'ollama'
 ? 'http://localhost:11434': t === 'anthropic'
 ? 'https://api.anthropic.com': 'https://api.openai.com/v1',
 organization_id: 'org-xxxxxxxxxxxx',
 bearer_token: '留空即不携带 Authorization',
 }
 return placeholders[key] ?? ''
}
// 测试 expose 方便 spec 直接操作
defineExpose({ selectedType })
</script>
<template>
 <form class="space-y-6" @submit.prevent="onSubmit">
 <!-- Provider 类型选择 -->
 <FormField v-slot="{ componentField }" name="provider_type">
 <FormItem>
 <FormLabel class="font-normal">
 Provider 类型
 </FormLabel>
 <FormControl>
 <Select
 v-bind="componentField"
 v-model="selectedType":disabled="props.mode === 'edit'"
 >
 <SelectTrigger>
 <SelectValue placeholder="请选择 Provider 类型" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="anthropic">
 Anthropic
 </SelectItem>
 <SelectItem value="openai_responses">
 OpenAI Responses
 </SelectItem>
 <SelectItem value="openai_chat">
 OpenAI Chat
 </SelectItem>
 <SelectItem value="gemini">
 Gemini
 </SelectItem>
 <SelectItem value="ollama">
 Ollama
 </SelectItem>
 </SelectContent>
 </Select>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 凭证名称 -->
 <FormField v-slot="{ componentField }" name="name">
 <FormItem>
 <FormLabel class="font-normal">
 凭证名称
 </FormLabel>
 <FormControl>
 <Input
 v-bind="componentField"
 placeholder="例如：openai-prod / anthropic-staging"
 />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 动态 config 字段（schema-driven） -->
 <div
 v-for="(prop, key) in schemaProperties":key="String(key)"
 class="space-y-1"
 >
 <FormField v-slot="{ componentField }":name="`config.${String(key)}`">
 <FormItem>
 <FormLabel class="font-normal">
 {{ (prop as JsonSchemaProperty).title ?? String(key) }}
 <span
 v-if="isOptional(prop as JsonSchemaProperty, String(key))"
 class="text-xs text-muted-foreground ml-1"
 >(可选)</span>
 </FormLabel>
 <FormControl>
 <div class="relative">
 <Input
 v-bind="componentField":type="isPasswordField(prop as JsonSchemaProperty) && !passwordVisible[String(key)]
 ? 'password': (isUriField(prop as JsonSchemaProperty) ? 'url': 'text')":placeholder="getPlaceholder(String(key))":autocomplete="isPasswordField(prop as JsonSchemaProperty) ? 'new-password': 'off'"
 />
 <button
 v-if="isPasswordField(prop as JsonSchemaProperty) && props.mode === 'edit'"
 type="button"
 class="absolute right-2 top-1/2 -translate-y-1/2 ":aria-label="passwordVisible[String(key)] ? '隐藏 API Key': '显示 API Key'"
 @click="togglePassword(String(key))"
 >
 <span:class="passwordVisible[String(key)] ? 'icon-[lucide--eye-off]': 'icon-[lucide--eye]'"
 class="w-4 "
 />
 </button>
 </div>
 </FormControl>
 <p
 v-if="(prop as JsonSchemaProperty).description"
 class="text-xs text-muted-foreground"
 >
 {{ (prop as JsonSchemaProperty).description }}
 </p>
 <FormMessage />
 </FormItem>
 </FormField>
 </div>
 <!-- 模型配置区域 -->
 <div class="space-y-3 rounded-lg border ">
 <div class="flex items-center justify-between">
 <h4 class="text-sm font-medium">
 支持的模型 <span class="text-xs text-destructive">*</span>
 </h4>
 <Button
 v-if="props.mode === 'edit'"
 type="button"
 variant="outline"
 size="sm":disabled="isFetchingModels"
 @click="handleFetchModels"
 >
 <span
 v-if="isFetchingModels"
 class="icon-[lucide--loader-2] mr-1 w-3 animate-spin"
 />
 <span v-else class="icon-[lucide--refresh-cw] mr-1 w-3" />
 {{ isFetchingModels ? '获取中...': '获取模型列表' }}
 </Button>
 </div>
 <!-- 获取到的模型列表（edit 模式） -->
 <div v-if="props.mode === 'edit' && fetchedModels.length > 0" class="space-y-2">
 <p class="text-xs text-muted-foreground">选择默认模型并测试:</p>
 <div class="flex flex-wrap gap-2">
 <div
 v-for="m in fetchedModels":key="m.id"
 class="flex items-center gap-1"
 >
 <button
 type="button"
 class="rounded-md border px-2 py-1 text-xs transition-colors":class="selectedDefaultModel === m.id
 ? 'border-primary bg-primary/10 text-primary': 'border-border hover:bg-accent'"
 @click="selectedDefaultModel = m.id; setValues({ default_model: m.id } as Record<string, unknown>, false)"
 >
 {{ m.display_name || m.id }}
 </button>
 <button
 type="button"
 class="rounded-md text-xs transition-colors hover:bg-accent":title="`测试模型 ${m.id}`"
 @click="testModel(m.id)"
 >
 <span
 v-if="testingModelId === m.id"
 class="icon-[lucide--loader-2] w-3 animate-spin text-muted-foreground"
 />
 <span
 v-else-if="modelTestResults[m.id]?.status === 'ok'"
 class="icon-[lucide--check] w-3 text-green-500"
 />
 <span
 v-else-if="modelTestResults[m.id]?.status === 'error'"
 class="icon-[lucide--x] w-3 text-destructive"
 />
 <span v-else class="icon-[lucide--zap] w-3 text-muted-foreground" />
 </button>
 </div>
 </div>
 </div>
 <!-- create 模式：手动输入 default_model -->
 <div v-if="props.mode === 'create'" class="space-y-2">
 <FormField v-slot="{ componentField }" name="default_model">
 <FormItem>
 <FormControl>
 <Input
 v-bind="componentField"
 placeholder="输入模型名称，例如: claude-3-5-sonnet-20241022"
 class="text-sm"
 />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <p class="text-xs text-muted-foreground">
 创建后可点击「获取模型列表」自动拉取该 Provider 支持的模型。
 </p>
 </div>
 <!-- edit 模式：错误提示 + 手动输入 -->
 <div v-if="props.mode === 'edit' && (fetchModelsError || showManualModelInput)" class="space-y-2">
 <p v-if="fetchModelsError" class="text-xs text-destructive">{{ fetchModelsError }}</p>
 <div class="flex gap-2">
 <Input
 v-model="manualModelName"
 placeholder="手动输入模型名称，例如: claude-3-5-sonnet-20241022"
 class="flex-1 text-sm"
 />
 <Button type="button" variant="secondary" size="sm" @click="confirmManualModel">
 确认
 </Button>
 </div>
 </div>
 <!-- 已选择的默认模型 -->
 <div v-if="selectedDefaultModel" class="text-xs text-muted-foreground">
 默认模型: <span class="font-medium text-foreground">{{ selectedDefaultModel }}</span>
 </div>
 </div>
 <!-- 操作按钮 -->
 <div class="flex justify-end gap-2 pt-4">
 <Button type="button" variant="ghost" @click="emit('cancel')">
 取消
 </Button>
 <Button type="submit" variant="default">
 {{ props.mode === 'create' ? '保存凭证': '更新凭证' }}
 </Button>
 </div>
 </form>
</template>
