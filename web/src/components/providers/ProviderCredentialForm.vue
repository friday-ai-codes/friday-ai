<script setup lang="ts">
import type {
  AvailableModel,
  InputModality,
  JsonSchemaProperty,
  ProviderCredentialCreatePayload,
  ProviderCredentialDto,
  ProviderCredentialUpdatePayload,
  ProviderType,
} from '~/types/providerCredential'
/**
 * Provider 凭证 schema-driven 动态表单（ + CONTEXT ~）
 *
 * 字段源：store.providerTypes[selectedType].credential_schema_json_schema.properties
 *
 * 动态分派规则（UI-SPEC §I-1）:
 *   - format=password 或 writeOnly=true → Input type=password + 眼睛 toggle（仅 edit 模式可切显）
 *   - format=uri                        → Input type=url + 提交前 new URL() try/catch 校验
 *   - anyOf: [string, null]             → optional string input（label 后缀 "(可选)"）
 *   - pattern                           → zod schema regex 校验
 *
 * Typography: 所有 FormLabel 显式 class="font-normal" 覆盖 shadcn-vue Label 默认 font-medium。
 * dirty state: meta.dirty 变化冒泡 emit('dirty') 供父容器弹"未保存修改"AlertDialog（UI-SPEC §I-5）。
 */
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { computed, ref, watch } from 'vue'
import * as z from 'zod'
import { providerCredentialsApi } from '~/api/providerCredentials'
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
import { useToast } from '~/composables/useToast'
import { useProviderCredentialStore } from '~/stores/providerCredential'

interface Props {
  initial?: ProviderCredentialDto
  mode: 'create' | 'edit'
  defaultScope?: 'system' | 'project'
  defaultProjectId?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  initial: undefined,
  defaultScope: 'system',
  defaultProjectId: null,
})

const emit = defineEmits<{
  (e: 'submit', payload: ProviderCredentialCreatePayload | ProviderCredentialUpdatePayload): void
  (e: 'cancel'): void
  (e: 'dirty', isDirty: boolean): void
}>()

const store = useProviderCredentialStore()
const toast = useToast()

// 模型获取状态
const isFetchingModels = ref(false)
const fetchModelsError = ref<string | null>(null)
// 编辑模式回显：后端已持久化的 available_models / default_model 直接落地，
// 用户无需重新点「获取模型列表」即可看到此前拉取过的清单与当前默认模型。
const fetchedModels = ref<AvailableModel[]>(
  normalizeModels(props.initial?.available_models ?? []),
)
const showManualModelInput = ref(false)
const manualModelName = ref('')
const selectedDefaultModel = ref(props.initial?.default_model ?? '')

// 模型测试状态
const testingModelId = ref<string | null>(null)
const modelTestResults = ref<Record<string, { status: 'ok' | 'error', latency_ms?: number, error?: string }>>({})

const editableModalities: Array<{ value: Exclude<InputModality, 'text'>, label: string, icon: string }> = [
  { value: 'image', label: '图片', icon: 'icon-[lucide--image]' },
  { value: 'pdf', label: 'PDF', icon: 'icon-[lucide--file-text]' },
  { value: 'audio', label: '音频', icon: 'icon-[lucide--audio-lines]' },
  { value: 'video', label: '视频', icon: 'icon-[lucide--video]' },
]

/** 上下文窗口预设（写 context_length，被后端上下文预算消费） */
const contextPresets: Array<{ value: number, label: string }> = [
  { value: 32_000, label: '32K' },
  { value: 128_000, label: '128K' },
  { value: 200_000, label: '200K' },
  { value: 256_000, label: '256K' },
  { value: 1_000_000, label: '1M' },
]

/** 自定义上下文输入态：modelId → 是否展示数字输入框 */
const customContextEditing = ref<Record<string, boolean>>({})

function formatContextLength(value: number): string {
  return value >= 1_000_000
    ? `${Math.round(value / 100_000) / 10}M`
    : `${Math.round(value / 1000)}K`
}

/**
 * 常见模型上下文预设（仅初始值，可改）：
 * deepseek-v4* / gemini-* → 1M；claude-* → 200K；gpt-* → 128K。
 */
function inferContextLength(modelId: string): number | undefined {
  const id = modelId.toLowerCase()
  if (id.startsWith('deepseek-v4'))
    return 1_000_000
  if (id.startsWith('gemini-'))
    return 1_000_000
  if (id.startsWith('claude-'))
    return 200_000
  if (id.startsWith('gpt-'))
    return 128_000
  return undefined
}

function contextSelectValue(m: AvailableModel): string {
  if (customContextEditing.value[m.id])
    return 'custom'
  const len = m.context_length
  if (typeof len !== 'number' || len <= 0)
    return ''
  return contextPresets.some(p => p.value === len) ? String(len) : 'custom'
}

function setModelContextLength(modelId: string, value: number | undefined) {
  fetchedModels.value = fetchedModels.value.map(model =>
    model.id === modelId
      ? { ...model, context_length: value, capability_source: 'manual' }
      : model,
  )
}

function onContextSelectChange(modelId: string, raw: string) {
  if (raw === 'custom') {
    customContextEditing.value = { ...customContextEditing.value, [modelId]: true }
    return
  }
  customContextEditing.value = { ...customContextEditing.value, [modelId]: false }
  const parsed = Number(raw)
  setModelContextLength(modelId, Number.isFinite(parsed) && parsed > 0 ? parsed : undefined)
}

function onCustomContextInput(modelId: string, raw: string) {
  const parsed = Number(raw)
  if (Number.isFinite(parsed) && parsed > 0)
    setModelContextLength(modelId, Math.floor(parsed))
}

/** 输出能力：是否支持图片生成（output_modalities 含 image） */
function modelHasImageOutput(m: AvailableModel): boolean {
  return Array.isArray(m.output_modalities) && m.output_modalities.includes('image')
}

function toggleModelImageOutput(modelId: string) {
  fetchedModels.value = fetchedModels.value.map((model) => {
    if (model.id !== modelId)
      return model
    const next: InputModality[] = modelHasImageOutput(model) ? ['text'] : ['text', 'image']
    return { ...model, output_modalities: next, capability_source: 'manual' }
  })
}

function normalizeInputModalities(value: unknown): InputModality[] {
  const allowed = new Set<InputModality>(['text', 'image', 'audio', 'video', 'pdf'])
  const raw = Array.isArray(value) ? value : []
  const result: InputModality[] = ['text']
  for (const item of raw) {
    const modality = String(item || '').trim().toLowerCase() as InputModality
    if (modality !== 'text' && allowed.has(modality) && !result.includes(modality))
      result.push(modality)
  }
  return result
}

function inferInputModalities(model: Partial<AvailableModel> & { id: string }): {
  modalities: InputModality[]
  source: string
} {
  if (model.input_modalities)
    return { modalities: normalizeInputModalities(model.input_modalities), source: 'manual' }
  if (typeof model.supports_vision === 'boolean') {
    return {
      modalities: model.supports_vision ? ['text', 'image'] : ['text'],
      source: 'legacy_supports_vision',
    }
  }
  const id = model.id.toLowerCase()
  if (id.startsWith('deepseek'))
    return { modalities: ['text'], source: 'known_rules' }
  if (id.startsWith('claude-'))
    return { modalities: ['text', 'image'], source: 'known_rules' }
  return { modalities: ['text'], source: 'manual_default' }
}

function normalizeModels(models: AvailableModel[]): AvailableModel[] {
  const seen = new Set<string>()
  const normalized: AvailableModel[] = []
  for (const model of models) {
    const id = String(model.id || '').trim()
    if (!id || seen.has(id))
      continue
    seen.add(id)
    const { modalities, source } = inferInputModalities({ ...model, id })
    normalized.push({
      ...model,
      id,
      display_name: String(model.display_name || id).trim(),
      // 常见模型上下文预设：仅在未配置时填充初始值（用户可改）
      context_length: typeof model.context_length === 'number' && model.context_length > 0
        ? model.context_length
        : inferContextLength(id),
      input_modalities: modalities,
      supports_vision: modalities.includes('image'),
      capability_source: model.capability_source || source,
    })
  }
  return normalized
}

function modelFromId(id: string): AvailableModel {
  const clean = id.trim()
  const { modalities, source } = inferInputModalities({ id: clean })
  return {
    id: clean,
    display_name: clean,
    context_length: inferContextLength(clean),
    input_modalities: modalities,
    supports_vision: modalities.includes('image'),
    capability_source: source,
  }
}

function addModelToList(modelId: string): boolean {
  const clean = modelId.trim()
  if (!clean)
    return false
  if (!fetchedModels.value.some(m => m.id === clean))
    fetchedModels.value = [...fetchedModels.value, modelFromId(clean)]
  return true
}

function modelsForSubmit(defaultModel: string): AvailableModel[] {
  const manual = manualModelName.value.trim()
  if (manual)
    addModelToList(manual)
  if (defaultModel)
    addModelToList(defaultModel)
  return normalizeModels(fetchedModels.value)
}

// 确保 providerTypes 就位（store 内部去重，重复调用无副作用）
if (store.providerTypes.length === 0) {
  store.fetchProviderTypes().catch(() => {
    // 错误由父组件通过 useErrorHandler 承接
  })
}

const selectedType = ref<ProviderType>(props.initial?.provider_type ?? 'anthropic')
const passwordVisible = ref<Record<string, boolean>>({})

const currentMeta = computed(() =>
  store.providerTypes.find(p => p.provider_type === selectedType.value),
)

const schemaProperties = computed<Record<string, JsonSchemaProperty>>(
  () => (currentMeta.value?.credential_schema_json_schema?.properties ?? {}) as Record<string, JsonSchemaProperty>,
)

const schemaRequired = computed<string[]>(
  () => currentMeta.value?.credential_schema_json_schema?.required ?? [],
)

function isPasswordField(prop: JsonSchemaProperty): boolean {
  if (prop.format === 'password' || prop.writeOnly)
    return true
  return (prop.anyOf ?? []).some(sub => sub.format === 'password' || sub.writeOnly === true)
}

function isUriField(prop: JsonSchemaProperty): boolean {
  if (prop.format === 'uri')
    return true
  return (prop.anyOf ?? []).some(sub => sub.format === 'uri')
}

function isOptional(prop: JsonSchemaProperty, key: string): boolean {
  if (!schemaRequired.value.includes(key))
    return true
  // anyOf 含 null 类型也视为可选
  return (prop.anyOf ?? []).some(sub => sub.type === 'null')
}

// ==== 动态 zod schema ====
const zodSchema = computed(() => {
  const shape: Record<string, z.ZodTypeAny> = {
    provider_type: z.enum(['anthropic', 'openai_responses', 'openai_chat', 'gemini', 'ollama']),
    name: z.string().min(1, '请输入凭证名称').max(100, '名称最长 100 字符'),
    scope: z.enum(['system', 'project']),
    scope_id: z.string().uuid('请选择有效空间').nullable().optional(),
    is_active: z.boolean().optional(),
    default_model: z.string().min(1, '请输入或选择一个模型'),
    // LLM 并发上限（0=不限）。number 输入控件给出字符串，用 coerce 归一。
    max_concurrency: z.coerce.number().int().min(0, '不能为负').optional(),
  }
  const configShape: Record<string, z.ZodTypeAny> = {}
  for (const [key, prop] of Object.entries(schemaProperties.value)) {
    let fieldSchema: z.ZodTypeAny = z.string()
    if (isUriField(prop)) {
      fieldSchema = z.string().refine((v: string) => {
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
      fieldSchema = z.string().regex(pat, `必须匹配 ${prop.pattern}`)
    }
    if (isOptional(prop, key))
      fieldSchema = (fieldSchema as z.ZodString).optional().or(z.literal(''))
    else
      fieldSchema = (fieldSchema as z.ZodString).min(1, `请输入${prop.title ?? key}`)
    configShape[key] = fieldSchema
  }
  shape.config = z.object(configShape)
  return z.object(shape)
})

const formSchema = computed(() => toTypedSchema(zodSchema.value))

const { handleSubmit, meta, setValues, values } = useForm({
  validationSchema: formSchema,
  initialValues: {
    provider_type: selectedType.value,
    name: props.initial?.name ?? '',
    scope: props.initial?.scope ?? props.defaultScope,
    scope_id: props.initial?.scope_id ?? props.defaultProjectId,
    is_active: props.initial?.is_active ?? true,
    default_model: props.initial?.default_model ?? '',
    max_concurrency: props.initial?.max_concurrency ?? 50,
    // edit 模式下回显已配置的 base_url / api_key（后端按写权限分级返回）。
    config: { ...(props.initial?.config ?? {}) } as Record<string, unknown>,
  },
})

// 切换 selectedType 时重置 config 字段集
watch(selectedType, (type) => {
  setValues({ provider_type: type, config: {} } as Record<string, unknown>, false)
})

// dirty 冒泡
watch(() => meta.value.dirty, (v) => {
  emit('dirty', v)
})

const onSubmit = handleSubmit((v) => {
  const defaultModel = (v.default_model as string)?.trim() || selectedDefaultModel.value || ''
  const availableModels = modelsForSubmit(defaultModel)
  if (!defaultModel || availableModels.length === 0) {
    toast.error('请至少添加一个模型')
    return
  }
  if (props.mode === 'create') {
    const payload: ProviderCredentialCreatePayload = {
      provider_type: v.provider_type as ProviderType,
      name: v.name as string,
      scope: v.scope as 'system' | 'project',
      scope_id: (v.scope_id as string | null | undefined) ?? null,
      config: (v.config as Record<string, unknown>) ?? {},
      is_active: (v.is_active as boolean | undefined) ?? true,
      default_model: defaultModel,
      available_models: availableModels,
      max_concurrency: (v.max_concurrency as number | undefined),
    }
    emit('submit', payload)
  }
  else {
    const configObj = (v.config as Record<string, unknown>) ?? {}
    const payload: ProviderCredentialUpdatePayload = {
      name: v.name as string,
      scope: v.scope as 'system' | 'project',
      scope_id: (v.scope_id as string | null | undefined) ?? null,
      config: Object.keys(configObj).length > 0 ? configObj : null,
      is_active: v.is_active as boolean | undefined,
      default_model: defaultModel,
      available_models: availableModels,
      max_concurrency: (v.max_concurrency as number | undefined),
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
    fetchedModels.value = normalizeModels(resp.available_models)
    if (resp.available_models.length === 0) {
      fetchModelsError.value = '未获取到模型列表，请手动输入一个模型名称'
      showManualModelInput.value = true
    }
    else {
      // 自动选择第一个模型作为 default_model
      selectedDefaultModel.value = resp.available_models[0].id
      setValues({ default_model: resp.available_models[0].id } as Record<string, unknown>, false)
      toast.success(`成功获取 ${resp.available_models.length} 个模型`)
    }
  }
  catch (e) {
    fetchModelsError.value = e instanceof Error ? e.message : '获取模型列表失败'
    showManualModelInput.value = true
  }
  finally {
    isFetchingModels.value = false
  }
}

/** 手动获取模型列表（用户主动触发） */
async function handleFetchModels() {
  if (!props.initial?.id)
    return
  await fetchModelsAfterCreate(props.initial.id)
}

/**
 * 新建模式：用当前表单 config（含 api_key/base_url）无状态拉模型。
 * 无需先保存凭证；成功后渲染可选列表并自动选第一个写入 default_model。
 */
async function handleFetchModelsCreate() {
  const config = (values.config ?? {}) as Record<string, unknown>
  isFetchingModels.value = true
  fetchModelsError.value = null
  try {
    const resp = await providerCredentialsApi.fetchModelsStateless({
      provider_type: selectedType.value,
      config,
    })
    fetchedModels.value = normalizeModels(resp.available_models)
    if (resp.available_models.length === 0) {
      fetchModelsError.value = resp.error || '未获取到模型，请手动输入模型名称'
      showManualModelInput.value = true
    }
    else {
      selectedDefaultModel.value = resp.available_models[0].id
      setValues({ default_model: resp.available_models[0].id } as Record<string, unknown>, false)
      toast.success(`成功获取 ${resp.available_models.length} 个模型`)
    }
  }
  catch (e) {
    fetchModelsError.value = e instanceof Error ? e.message : '获取模型列表失败'
    showManualModelInput.value = true
  }
  finally {
    isFetchingModels.value = false
  }
}

/** 选中某个模型作为默认模型（同步写回表单 default_model）。 */
function selectModel(id: string) {
  selectedDefaultModel.value = id
  setValues({ default_model: id } as Record<string, unknown>, false)
}

/** 切换到手动输入模型名称。 */
function showManual() {
  showManualModelInput.value = true
}

function onManualDefaultInput(value: string) {
  selectedDefaultModel.value = value
  setValues({ default_model: value } as Record<string, unknown>, false)
}

/** 确认手动输入的模型 */
function confirmManualModel() {
  if (!manualModelName.value.trim()) {
    toast.error('请输入模型名称')
    return
  }
  const modelName = manualModelName.value.trim()
  addModelToList(modelName)
  selectedDefaultModel.value = modelName
  setValues({ default_model: modelName } as Record<string, unknown>, false)
  showManualModelInput.value = false
  manualModelName.value = ''
  toast.success(`已设置默认模型: ${modelName}`)
}

function removeModel(modelId: string) {
  if (fetchedModels.value.length <= 1) {
    toast.error('至少保留一个模型')
    return
  }
  fetchedModels.value = fetchedModels.value.filter(m => m.id !== modelId)
  if (selectedDefaultModel.value === modelId) {
    const nextModel = fetchedModels.value[0]?.id ?? ''
    selectedDefaultModel.value = nextModel
    setValues({ default_model: nextModel } as Record<string, unknown>, false)
  }
}

function modelHasModality(model: AvailableModel, modality: InputModality): boolean {
  return normalizeInputModalities(model.input_modalities).includes(modality)
}

function toggleModelModality(modelId: string, modality: Exclude<InputModality, 'text'>) {
  fetchedModels.value = fetchedModels.value.map((model) => {
    if (model.id !== modelId)
      return model
    const modalities = normalizeInputModalities(model.input_modalities)
    const next = modalities.includes(modality)
      ? modalities.filter(item => item !== modality)
      : [...modalities, modality]
    return {
      ...model,
      input_modalities: normalizeInputModalities(next),
      supports_vision: next.includes('image'),
      capability_source: 'manual',
    }
  })
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
      [modelId]: { status: 'error', error: e instanceof Error ? e.message : '测试失败' },
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
      ? 'sk-ant-api03-xxxxxxxxxxxx'
      : t === 'gemini'
        ? 'AIzaSyxxxxxxxxxxxxxxxx'
        : 'sk-xxxxxxxxxxxxxxxx',
    base_url: t === 'ollama'
      ? 'http://localhost:11434'
      : t === 'anthropic'
        ? 'https://api.anthropic.com'
        : 'https://api.openai.com/v1',
    organization_id: 'org-xxxxxxxxxxxx',
    bearer_token: '留空即不携带 Authorization',
  }
  return placeholders[key] ?? ''
}

// 测试 expose 方便 spec 直接操作
defineExpose({ selectedType, onSubmit })
</script>

<template>
  <form class="flex min-h-0 flex-1 flex-col" @submit.prevent="onSubmit">
    <!-- 滚动主体 -->
    <div class="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
      <!-- 基础信息：Provider 类型 + 凭证名称 -->
      <div class="grid gap-4 sm:grid-cols-2">
        <FormField v-slot="{ componentField }" name="provider_type">
          <FormItem>
            <FormLabel class="font-normal">
              Provider 类型
            </FormLabel>
            <FormControl>
              <Select
                v-bind="componentField"
                v-model="selectedType"
                :disabled="props.mode === 'edit'"
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

        <FormField v-slot="{ componentField }" name="max_concurrency">
          <FormItem>
            <FormLabel class="font-normal">
              并发上限
              <span class="text-xs text-muted-foreground ml-1">（0 = 不限，默认 50）</span>
            </FormLabel>
            <FormControl>
              <Input
                v-bind="componentField"
                type="number"
                min="0"
                placeholder="50"
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>
      </div>

      <!-- 动态 config 字段（schema-driven） -->
      <div class="space-y-4">
        <FormField
          v-for="(prop, key) in schemaProperties"
          :key="String(key)"
          v-slot="{ componentField }"
          :name="`config.${String(key)}`"
        >
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
                  v-bind="componentField"
                  :type="isPasswordField(prop as JsonSchemaProperty) && !passwordVisible[String(key)]
                    ? 'password'
                    : (isUriField(prop as JsonSchemaProperty) ? 'url' : 'text')"
                  :placeholder="getPlaceholder(String(key))"
                  :autocomplete="isPasswordField(prop as JsonSchemaProperty) ? 'new-password' : 'off'"
                  :class="isPasswordField(prop as JsonSchemaProperty) && props.mode === 'edit' ? 'pr-10' : ''"
                />
                <button
                  v-if="isPasswordField(prop as JsonSchemaProperty) && props.mode === 'edit'"
                  type="button"
                  class="absolute right-1 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  :aria-label="passwordVisible[String(key)] ? '隐藏 API Key' : '显示 API Key'"
                  @click="togglePassword(String(key))"
                >
                  <span
                    :class="passwordVisible[String(key)] ? 'icon-[lucide--eye-off]' : 'icon-[lucide--eye]'"
                    class="h-4 w-4"
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
      <div class="overflow-hidden rounded-xl border border-border/60">
        <div class="flex items-center justify-between gap-2 border-b border-border/50 bg-muted/20 px-4 py-3">
          <div class="flex items-center gap-2">
            <span class="icon-[lucide--boxes] h-4 w-4 text-primary" aria-hidden="true" />
            <h4 class="text-sm font-semibold text-foreground">
              支持的模型
            </h4>
            <span class="text-destructive" aria-hidden="true">*</span>
          </div>
          <div class="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              class="h-8"
              @click="showManual"
            >
              <span class="icon-[lucide--plus] mr-1.5 h-3.5 w-3.5" />
              添加模型
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              class="h-8"
              :disabled="isFetchingModels"
              @click="props.mode === 'create' ? handleFetchModelsCreate() : handleFetchModels()"
            >
              <span
                v-if="isFetchingModels"
                class="icon-[lucide--loader-2] mr-1.5 h-3.5 w-3.5 animate-spin"
              />
              <span v-else class="icon-[lucide--refresh-cw] mr-1.5 h-3.5 w-3.5" />
              {{ isFetchingModels ? '获取中…' : (fetchedModels.length > 0 ? '刷新模型' : '获取模型列表') }}
            </Button>
          </div>
        </div>

        <div class="space-y-3 p-4">
          <!-- 已获取的模型：可选卡片网格 -->
          <div v-if="fetchedModels.length > 0" class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div
              v-for="m in fetchedModels"
              :key="m.id"
              class="group/chip flex cursor-pointer flex-col gap-2 rounded-lg border px-3 py-2 transition-all"
              :class="selectedDefaultModel === m.id
                ? 'border-primary bg-primary/5 ring-1 ring-primary/15'
                : 'border-border/60 hover:border-border hover:bg-accent/40'"
              @click="selectModel(m.id)"
            >
              <div class="flex w-full items-center justify-between gap-2">
                <span class="flex min-w-0 items-center gap-2">
                  <span
                    class="h-4 w-4 shrink-0"
                    :class="selectedDefaultModel === m.id
                      ? 'icon-[lucide--circle-check] text-primary'
                      : 'icon-[lucide--circle] text-muted-foreground/40'"
                    aria-hidden="true"
                  />
                  <span
                    class="truncate text-xs font-medium"
                    :class="selectedDefaultModel === m.id ? 'text-primary' : 'text-foreground'"
                  >
                    {{ m.display_name || m.id }}
                  </span>
                </span>
                <span class="flex shrink-0 items-center gap-1">
                  <button
                    v-if="props.mode === 'edit'"
                    type="button"
                    class="rounded-md p-1 transition-colors hover:bg-background"
                    :title="`测试模型 ${m.id} 连接`"
                    @click.stop="testModel(m.id)"
                  >
                    <span
                      v-if="testingModelId === m.id"
                      class="icon-[lucide--loader-2] h-3.5 w-3.5 animate-spin text-muted-foreground"
                    />
                    <span
                      v-else-if="modelTestResults[m.id]?.status === 'ok'"
                      class="icon-[lucide--circle-check] h-3.5 w-3.5 text-emerald-500"
                    />
                    <span
                      v-else-if="modelTestResults[m.id]?.status === 'error'"
                      class="icon-[lucide--circle-x] h-3.5 w-3.5 text-destructive"
                    />
                    <span v-else class="icon-[lucide--zap] h-3.5 w-3.5 text-muted-foreground/60" />
                  </button>
                  <button
                    type="button"
                    class="rounded-md p-1 text-muted-foreground transition-colors hover:bg-background hover:text-destructive"
                    :title="`移除模型 ${m.id}`"
                    @click.stop="removeModel(m.id)"
                  >
                    <span class="icon-[lucide--x] h-3.5 w-3.5" />
                  </button>
                </span>
              </div>
              <div class="flex w-full flex-wrap gap-1">
                <button
                  v-for="modality in editableModalities"
                  :key="`${m.id}-${modality.value}`"
                  type="button"
                  class="inline-flex h-6 items-center gap-1 rounded-md border px-1.5 text-[11px] transition-colors"
                  :class="modelHasModality(m, modality.value)
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-border/60 bg-background/70 text-muted-foreground hover:text-foreground'"
                  :title="`${modelHasModality(m, modality.value) ? '关闭' : '开启'}${modality.label}输入`"
                  @click.stop="toggleModelModality(m.id, modality.value)"
                >
                  <span :class="`${modality.icon} h-3 w-3`" />
                  <span>{{ modality.label }}</span>
                </button>
                <!-- 输出能力：图片生成 -->
                <button
                  type="button"
                  class="inline-flex h-6 items-center gap-1 rounded-md border px-1.5 text-[11px] transition-colors"
                  :class="modelHasImageOutput(m)
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-border/60 bg-background/70 text-muted-foreground hover:text-foreground'"
                  :title="`${modelHasImageOutput(m) ? '关闭' : '开启'}图片生成输出`"
                  @click.stop="toggleModelImageOutput(m.id)"
                >
                  <span class="icon-[lucide--image-plus] h-3 w-3" />
                  <span>生成图片</span>
                </button>
              </div>
              <!-- 上下文窗口 -->
              <div class="flex w-full items-center gap-1.5" @click.stop>
                <span class="icon-[lucide--ruler] h-3 w-3 shrink-0 text-muted-foreground/60" />
                <span class="shrink-0 text-[11px] text-muted-foreground">上下文</span>
                <select
                  class="h-6 rounded-md border border-border/60 bg-background/70 px-1 text-[11px] text-foreground outline-none transition-colors hover:border-border"
                  :value="contextSelectValue(m)"
                  :title="m.context_length ? `上下文窗口：${m.context_length.toLocaleString()} tokens` : '未设置，使用系统默认'"
                  @change="onContextSelectChange(m.id, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">
                    默认
                  </option>
                  <option v-for="p in contextPresets" :key="p.value" :value="String(p.value)">
                    {{ p.label }}
                  </option>
                  <option value="custom">
                    自定义…
                  </option>
                </select>
                <Input
                  v-if="customContextEditing[m.id]"
                  type="number"
                  class="h-6 w-28 px-1.5 text-[11px]"
                  placeholder="tokens 数"
                  :model-value="m.context_length ?? ''"
                  @click.stop
                  @update:model-value="onCustomContextInput(m.id, String($event))"
                />
                <span
                  v-else-if="typeof m.context_length === 'number' && m.context_length > 0"
                  class="text-[11px] text-muted-foreground"
                >
                  {{ formatContextLength(m.context_length) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 空态：尚未获取模型 -->
          <div
            v-else-if="!showManualModelInput && !fetchModelsError"
            class="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border/60 bg-muted/20 py-6 text-center"
          >
            <span class="icon-[lucide--package-open] h-7 w-7 text-muted-foreground/40" aria-hidden="true" />
            <p class="px-4 text-xs text-muted-foreground">
              填好 API Key 与 Base URL 后点击右上角「获取模型列表」自动拉取
            </p>
            <button
              type="button"
              class="text-xs font-medium text-primary transition-colors hover:text-primary/80"
              @click="showManual"
            >
              或手动输入模型名称
            </button>
          </div>

          <!-- create 模式手动输入（受 zod default_model 校验） -->
          <FormField
            v-if="props.mode === 'create' && (showManualModelInput || fetchModelsError)"
            v-slot="{ componentField }"
            name="default_model"
          >
            <FormItem>
              <FormControl>
                <Input
                  v-bind="componentField"
                  placeholder="输入模型名称，例如: claude-3-5-sonnet-20241022"
                  class="text-sm"
                  @input="onManualDefaultInput(($event.target as HTMLInputElement).value)"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          </FormField>

          <!-- edit 模式手动输入 -->
          <div
            v-if="props.mode === 'edit' && (showManualModelInput || fetchModelsError)"
            class="flex gap-2"
          >
            <Input
              v-model="manualModelName"
              placeholder="手动输入模型名称，例如: claude-3-5-sonnet-20241022"
              class="flex-1 text-sm"
            />
            <Button type="button" variant="secondary" size="sm" @click="confirmManualModel">
              确认
            </Button>
          </div>

          <!-- 错误提示 -->
          <p v-if="fetchModelsError" class="flex items-center gap-1.5 text-xs text-destructive">
            <span class="icon-[lucide--triangle-alert] h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            {{ fetchModelsError }}
          </p>

          <!-- 已选择的默认模型 -->
          <div
            v-if="selectedDefaultModel"
            class="flex items-center gap-1.5 rounded-md bg-primary/5 px-2.5 py-1.5 text-xs"
          >
            <span class="icon-[lucide--check] h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
            <span class="text-muted-foreground">默认模型</span>
            <span class="truncate font-medium text-foreground">{{ selectedDefaultModel }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 固定底部操作栏 -->
    <div class="flex items-center justify-end gap-2 border-t border-border/50 bg-muted/20 px-6 py-4">
      <Button type="button" variant="ghost" @click="emit('cancel')">
        取消
      </Button>
      <Button type="submit" variant="default">
        <span
          :class="props.mode === 'create' ? 'icon-[lucide--check]' : 'icon-[lucide--save]'"
          class="mr-1.5 h-4 w-4"
          aria-hidden="true"
        />
        {{ props.mode === 'create' ? '保存凭证' : '更新凭证' }}
      </Button>
    </div>
  </form>
</template>
