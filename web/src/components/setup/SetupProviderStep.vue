<script setup lang="ts">
import type { PresetModel, ProviderPreset } from '~/lib/providerPresets'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { computed, ref } from 'vue'
import * as z from 'zod'
import { providerCredentialsApi } from '~/api/providerCredentials'
import { setupProvider } from '~/api/setup'
import { Button } from '~/components/ui/button'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '~/components/ui/form'
import { Input } from '~/components/ui/input'
import { DEFAULT_PRESET, PROVIDER_PRESETS } from '~/lib/providerPresets'

const props = withDefaults(defineProps<{ showPrev?: boolean }>(), { showPrev: false })
const emit = defineEmits<{ done: [], skip: [], prev: [] }>()
const { t } = useI18n()

const selectedPresetId = ref(DEFAULT_PRESET.id)
const submitError = ref<string | null>(null)
const isSubmitting = ref(false)

// 模型清单（本地状态，预设加载 / 获取 / 手动增删都改这里）
const models = ref<PresetModel[]>(DEFAULT_PRESET.models.map(m => ({ ...m })))
const selectedModelId = ref<string>(DEFAULT_PRESET.models[0]?.id ?? '')
const manualModel = ref('')
const isFetchingModels = ref(false)
const fetchModelsError = ref<string | null>(null)

const selectedPreset = computed<ProviderPreset>(
  () => PROVIDER_PRESETS.find(p => p.id === selectedPresetId.value) ?? DEFAULT_PRESET,
)

const formSchema = toTypedSchema(z.object({
  baseUrl: z.string().min(1, t('setup.provider.validation.baseUrlRequired')),
  apiKey: z.string().min(1, t('setup.provider.validation.apiKeyRequired')),
}))

const { handleSubmit, setFieldValue, values } = useForm({
  validationSchema: formSchema,
  initialValues: {
    baseUrl: DEFAULT_PRESET.baseUrl,
    apiKey: '',
  },
})

function selectPreset(preset: ProviderPreset) {
  selectedPresetId.value = preset.id
  setFieldValue('baseUrl', preset.baseUrl)
  models.value = preset.models.map(m => ({ ...m }))
  selectedModelId.value = preset.models[0]?.id ?? ''
  fetchModelsError.value = null
}

function selectModel(id: string) {
  selectedModelId.value = id
}

function removeModel(id: string) {
  models.value = models.value.filter(m => m.id !== id)
  if (selectedModelId.value === id)
    selectedModelId.value = models.value[0]?.id ?? ''
}

function addModel(id: string, contextLength: number | null = null, supportsVision = false): void {
  const clean = id.trim()
  if (!clean)
    return
  if (!models.value.some(m => m.id === clean)) {
    models.value = [
      ...models.value,
      { id: clean, contextLength: contextLength ?? inferContextLength(clean), supportsVision },
    ]
  }
  selectedModelId.value = clean
}

/** 上下文窗口预设（写 context_length，被后端上下文预算消费） */
const contextPresets: Array<{ value: number, label: string }> = [
  { value: 32_000, label: '32K' },
  { value: 128_000, label: '128K' },
  { value: 200_000, label: '200K' },
  { value: 256_000, label: '256K' },
  { value: 1_000_000, label: '1M' },
]

/** 常见模型上下文预设（仅初始值，可改） */
function inferContextLength(modelId: string): number | null {
  const id = modelId.toLowerCase()
  if (id.startsWith('deepseek-v4') || id.startsWith('gemini-'))
    return 1_000_000
  if (id.startsWith('claude-'))
    return 200_000
  if (id.startsWith('gpt-'))
    return 128_000
  return null
}

function contextSelectValue(m: PresetModel): string {
  return m.contextLength && m.contextLength > 0 ? String(m.contextLength) : ''
}

function isNonPresetContext(m: PresetModel): boolean {
  return Boolean(
    m.contextLength
    && m.contextLength > 0
    && !contextPresets.some(p => p.value === m.contextLength),
  )
}

function onContextChange(modelId: string, raw: string) {
  const parsed = Number(raw)
  const next = Number.isFinite(parsed) && parsed > 0 ? parsed : null
  models.value = models.value.map(m =>
    m.id === modelId ? { ...m, contextLength: next } : m,
  )
}

function confirmManualModel() {
  const clean = manualModel.value.trim()
  if (!clean)
    return
  addModel(clean)
  manualModel.value = ''
}

function formatContext(n: number | null): string {
  if (!n)
    return ''
  if (n >= 1_000_000)
    return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`
  return n >= 1000 ? `${Math.round(n / 1000)}K` : String(n)
}

/** 获取模型列表：与系统设置新建 Provider 完全一致的无状态拉取逻辑。 */
async function handleFetchModels() {
  const baseUrl = String(values.baseUrl ?? '').trim()
  const apiKey = String(values.apiKey ?? '').trim()
  if (!baseUrl || !apiKey) {
    fetchModelsError.value = t('setup.provider.models.needCredentials')
    return
  }
  isFetchingModels.value = true
  fetchModelsError.value = null
  try {
    const resp = await providerCredentialsApi.fetchModelsStateless({
      provider_type: 'anthropic',
      config: { api_key: apiKey, base_url: baseUrl },
    })
    if (resp.available_models.length === 0) {
      fetchModelsError.value = resp.error || t('setup.provider.models.empty')
    }
    else {
      models.value = resp.available_models.map(m => ({
        id: m.id,
        // 上游未返回 context_length 时按常见模型预设填充（可改）
        contextLength: m.context_length ?? inferContextLength(m.id),
        supportsVision: Boolean(m.supports_vision),
      }))
      selectedModelId.value = resp.available_models[0].id
    }
  }
  catch (e) {
    fetchModelsError.value = e instanceof Error ? e.message : t('setup.provider.models.fetchFailed')
  }
  finally {
    isFetchingModels.value = false
  }
}

const onSubmit = handleSubmit(async (formValues) => {
  submitError.value = null
  if (!selectedModelId.value || models.value.length === 0) {
    submitError.value = t('setup.provider.models.required')
    return
  }
  isSubmitting.value = true
  try {
    await setupProvider({
      api_key: formValues.apiKey,
      base_url: formValues.baseUrl,
      name: selectedPreset.value.id,
      model: selectedModelId.value,
      default_model: selectedModelId.value,
      models: models.value.map(m => ({
        id: m.id,
        context_length: m.contextLength ?? undefined,
        supports_vision: m.supportsVision,
      })),
    })
    emit('done')
  }
  catch (e: unknown) {
    submitError.value = e instanceof Error ? e.message : t('setup.provider.error.default')
  }
  finally {
    isSubmitting.value = false
  }
})
</script>

<template>
  <div>
    <div class="mb-6 text-center">
      <div class="inline-flex items-center justify-center p-3 mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
        <span class="icon-[lucide--sparkles] text-3xl text-primary" />
      </div>
      <h1 class="text-2xl font-bold text-foreground mb-1">
        {{ t('setup.provider.title') }}
      </h1>
      <p class="text-sm text-muted-foreground">
        {{ t('setup.provider.subtitle') }}
      </p>
    </div>

    <div
      v-if="submitError"
      class="flex items-start gap-2.5 p-3 rounded-xl bg-destructive/8 border border-destructive/15 text-destructive mb-5"
    >
      <span class="icon-[lucide--alert-circle] text-base flex-shrink-0 mt-0.5" />
      <span class="text-sm">{{ submitError }}</span>
    </div>

    <form class="space-y-4" @submit="onSubmit">
      <!-- 供应商预设选择 -->
      <div class="space-y-2">
        <p class="text-sm font-medium text-foreground/80">
          {{ t('setup.provider.presetLabel') }}
        </p>
        <div class="grid grid-cols-1 gap-2">
          <button
            v-for="preset in PROVIDER_PRESETS"
            :key="preset.id"
            type="button"
            class="text-left rounded-xl border p-3 transition-colors"
            :class="preset.id === selectedPresetId
              ? 'border-primary bg-primary/5'
              : 'border-border/60 hover:border-border bg-card/40'"
            @click="selectPreset(preset)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-medium text-foreground">{{ preset.label }}</span>
              <span
                v-if="preset.id === selectedPresetId"
                class="icon-[lucide--check-circle-2] text-primary text-base flex-shrink-0"
              />
            </div>
            <p class="mt-1 text-xs text-muted-foreground/80">
              {{ preset.description }}
            </p>
          </button>
        </div>
      </div>

      <!-- 获取 API Key 引导 -->
      <p
        v-if="selectedPreset.apiKeyUrl"
        class="flex items-center gap-1.5 text-xs text-muted-foreground"
      >
        <span class="icon-[lucide--info] text-sm flex-shrink-0" />
        <span>{{ t('setup.provider.apiKeyGuide', { provider: selectedPreset.label }) }}</span>
        <a
          :href="selectedPreset.apiKeyUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-0.5 text-primary hover:underline"
        >
          {{ t('setup.provider.apiKeyGuideLink') }}
          <span class="icon-[lucide--external-link] text-[0.7rem]" />
        </a>
      </p>

      <FormField v-slot="{ componentField }" name="baseUrl">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.provider.fields.baseUrl') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="text"
                placeholder="https://api.anthropic.com"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <FormField v-slot="{ componentField }" name="apiKey">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.provider.fields.apiKey') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key-round] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="password"
                :placeholder="t('setup.provider.fields.apiKeyPlaceholder')"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <!-- 模型清单：选择默认模型 + 获取 / 手动增删 -->
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <p class="text-sm font-medium text-foreground/80">
            {{ t('setup.provider.models.label') }}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            class="h-7 text-xs"
            :disabled="isFetchingModels"
            @click="handleFetchModels"
          >
            <span
              v-if="isFetchingModels"
              class="icon-[lucide--loader-circle] mr-1.5 animate-spin"
            />
            <span v-else class="icon-[lucide--refresh-cw] mr-1.5" />
            {{ isFetchingModels ? t('setup.provider.models.fetching') : t('setup.provider.models.fetch') }}
          </Button>
        </div>

        <div v-if="models.length > 0" class="grid grid-cols-1 gap-1.5">
          <button
            v-for="m in models"
            :key="m.id"
            type="button"
            class="flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left transition-colors"
            :class="m.id === selectedModelId
              ? 'border-primary bg-primary/5'
              : 'border-border/60 hover:border-border bg-card/40'"
            @click="selectModel(m.id)"
          >
            <span class="flex min-w-0 items-center gap-2">
              <span
                class="h-3.5 w-3.5 flex-shrink-0"
                :class="m.id === selectedModelId
                  ? 'icon-[lucide--circle-check] text-primary'
                  : 'icon-[lucide--circle] text-muted-foreground/40'"
              />
              <span class="truncate text-sm" :class="m.id === selectedModelId ? 'text-primary font-medium' : 'text-foreground'">
                {{ m.id }}
              </span>
            </span>
            <span class="flex flex-shrink-0 items-center gap-1.5">
              <!-- 上下文窗口：预设可改（默认 = 跟随系统） -->
              <select
                class="h-6 rounded-md border border-border/60 bg-background/70 px-1 text-xs text-muted-foreground outline-none transition-colors hover:border-border"
                :value="contextSelectValue(m)"
                :title="m.contextLength ? `上下文窗口：${m.contextLength.toLocaleString()} tokens` : '上下文窗口：未设置'"
                :aria-label="`${m.id} 上下文窗口`"
                @click.stop
                @change="onContextChange(m.id, ($event.target as HTMLSelectElement).value)"
              >
                <option value="">
                  默认
                </option>
                <option v-if="isNonPresetContext(m)" :value="String(m.contextLength)">
                  {{ formatContext(m.contextLength) }}
                </option>
                <option v-for="p in contextPresets" :key="p.value" :value="String(p.value)">
                  {{ p.label }}
                </option>
              </select>
              <span
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs"
                :class="m.supportsVision ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'"
              >
                <span :class="m.supportsVision ? 'icon-[lucide--image]' : 'icon-[lucide--type]'" class="text-[0.7rem]" />
                {{ m.supportsVision ? t('setup.provider.caps.vision') : t('setup.provider.caps.textOnly') }}
              </span>
              <span
                class="icon-[lucide--x] text-sm text-muted-foreground hover:text-destructive"
                role="button"
                :aria-label="`移除 ${m.id}`"
                @click.stop="removeModel(m.id)"
              />
            </span>
          </button>
        </div>

        <p
          v-else
          class="rounded-lg border border-dashed border-border/60 bg-muted/20 px-3 py-3 text-center text-xs text-muted-foreground"
        >
          {{ t('setup.provider.models.empty') }}
        </p>

        <!-- 手动添加模型 -->
        <div class="flex gap-2">
          <Input
            v-model="manualModel"
            :placeholder="t('setup.provider.models.manualPlaceholder')"
            class="flex-1 text-sm"
            @keydown.enter.prevent="confirmManualModel"
          />
          <Button type="button" variant="secondary" size="sm" @click="confirmManualModel">
            {{ t('setup.provider.models.add') }}
          </Button>
        </div>

        <p v-if="fetchModelsError" class="flex items-center gap-1.5 text-xs text-destructive">
          <span class="icon-[lucide--triangle-alert] flex-shrink-0" />
          {{ fetchModelsError }}
        </p>
      </div>

      <!-- 导航：上一步 / 跳过 / 完成 -->
      <div class="flex items-center gap-2 pt-2">
        <Button
          v-if="props.showPrev"
          type="button"
          variant="outline"
          class="h-10"
          :disabled="isSubmitting"
          @click="emit('prev')"
        >
          <span class="icon-[lucide--arrow-left] mr-1.5" />
          {{ t('setup.nav.prev') }}
        </Button>
        <Button
          type="button"
          variant="ghost"
          class="h-10"
          :disabled="isSubmitting"
          @click="emit('skip')"
        >
          {{ t('setup.nav.skip') }}
        </Button>
        <Button
          type="submit"
          class="h-10 flex-1 text-sm font-semibold"
          :disabled="isSubmitting"
        >
          <template v-if="isSubmitting">
            <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
            {{ t('setup.provider.testing') }}
          </template>
          <template v-else>
            <span class="icon-[lucide--plug-zap] mr-2" />
            {{ t('setup.provider.cta') }}
          </template>
        </Button>
      </div>
    </form>
  </div>
</template>
