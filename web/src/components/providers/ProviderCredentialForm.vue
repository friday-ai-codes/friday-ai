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
 scope_id: z.string.uuid('请选择有效项目').nullable.optional,
 is_active: z.boolean.optional,
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
 config: {} as Record<string, unknown>,
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
 if (props.mode === 'create') {
 const payload: ProviderCredentialCreatePayload = {
 provider_type: v.provider_type as ProviderType,
 name: v.name as string,
 scope: v.scope as 'system' | 'project',
 scope_id: (v.scope_id as string | null | undefined) ?? null,
 config: (v.config as Record<string, unknown>) ?? {},
 is_active: (v.is_active as boolean | undefined) ?? true,
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
 emit('submit', payload)
 }
})
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
