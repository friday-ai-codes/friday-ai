<script setup lang="ts">
import type { ProviderPreset } from '~/lib/providerPresets'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import * as z from 'zod'
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

const emit = defineEmits<{ done: [], skip: [] }>()
const { t } = useI18n()

const selectedPresetId = ref(DEFAULT_PRESET.id)
const submitError = ref<string | null>(null)
const isSubmitting = ref(false)

const selectedPreset = computed<ProviderPreset>(
  () => PROVIDER_PRESETS.find(p => p.id === selectedPresetId.value) ?? DEFAULT_PRESET,
)

const formSchema = toTypedSchema(z.object({
  baseUrl: z.string().min(1, t('setup.provider.validation.baseUrlRequired')),
  model: z.string().min(1, t('setup.provider.validation.modelRequired')),
  apiKey: z.string().min(1, t('setup.provider.validation.apiKeyRequired')),
}))

const { handleSubmit, setFieldValue } = useForm({
  validationSchema: formSchema,
  initialValues: {
    baseUrl: DEFAULT_PRESET.baseUrl,
    model: DEFAULT_PRESET.model,
    apiKey: '',
  },
})

function selectPreset(preset: ProviderPreset) {
  selectedPresetId.value = preset.id
  // 预设自动填充 base_url + model（仍可编辑纠错）；自定义预设清空待用户填写
  setFieldValue('baseUrl', preset.baseUrl)
  setFieldValue('model', preset.model)
}

function formatContext(n: number | null): string {
  if (!n)
    return ''
  return n >= 1000 ? `${Math.round(n / 1000)}K` : String(n)
}

const onSubmit = handleSubmit(async (formValues) => {
  submitError.value = null
  isSubmitting.value = true
  try {
    await setupProvider({
      api_key: formValues.apiKey,
      base_url: formValues.baseUrl,
      model: formValues.model,
      context_length: selectedPreset.value.contextLength ?? undefined,
      supports_vision: selectedPreset.value.supportsVision,
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
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span
                v-if="preset.contextLength"
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground"
              >
                <span class="icon-[lucide--file-text] text-[0.7rem]" />
                {{ t('setup.provider.caps.context', { n: formatContext(preset.contextLength) }) }}
              </span>
              <span
                v-if="!preset.custom"
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs"
                :class="preset.supportsVision ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'"
              >
                <span :class="preset.supportsVision ? 'icon-[lucide--image]' : 'icon-[lucide--type]'" class="text-[0.7rem]" />
                {{ preset.supportsVision ? t('setup.provider.caps.vision') : t('setup.provider.caps.textOnly') }}
              </span>
              <span class="text-xs text-muted-foreground/80">{{ preset.description }}</span>
            </div>
          </button>
        </div>
      </div>

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

      <FormField v-slot="{ componentField }" name="model">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.provider.fields.model') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--cpu] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="text"
                placeholder="claude-sonnet-4-5"
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

      <Button
        type="submit"
        class="w-full h-10 text-sm font-semibold mt-2"
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

      <button
        type="button"
        class="w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors pt-1"
        :disabled="isSubmitting"
        @click="emit('skip')"
      >
        {{ t('setup.provider.skip') }}
      </button>
    </form>
  </div>
</template>
