<script setup lang="ts">
import type { SetupRagRequest } from '~/api/setup'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { ref } from 'vue'
import * as z from 'zod'
import { setupRag } from '~/api/setup'
import { Button } from '~/components/ui/button'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '~/components/ui/form'
import { Input } from '~/components/ui/input'

const emit = defineEmits<{ done: [], skip: [] }>()
const { t } = useI18n()

const submitError = ref<string | null>(null)
const isSubmitting = ref(false)

const formSchema = toTypedSchema(z.object({
  qdrantUrl: z.string().min(1, t('setup.rag.validation.qdrantUrlRequired')),
  qdrantApiKey: z.string().optional(),
  embeddingApiUrl: z.string().optional(),
  embeddingApiKey: z.string().optional(),
  embeddingModel: z.string().optional(),
  // 数字输入框的值可能为 string 或 number，统一接收后在提交时归一
  embeddingDimension: z.union([z.string(), z.number()]).optional(),
}))

const { handleSubmit } = useForm({
  validationSchema: formSchema,
  initialValues: {
    qdrantUrl: 'http://qdrant:6333',
    qdrantApiKey: '',
    embeddingApiUrl: '',
    embeddingApiKey: '',
    embeddingModel: '',
    embeddingDimension: '',
  },
})

const onSubmit = handleSubmit(async (formValues) => {
  submitError.value = null
  isSubmitting.value = true
  try {
    const payload: SetupRagRequest = { qdrant_url: formValues.qdrantUrl }
    if (formValues.qdrantApiKey?.trim())
      payload.qdrant_api_key = formValues.qdrantApiKey.trim()
    if (formValues.embeddingApiUrl?.trim())
      payload.embedding_api_url = formValues.embeddingApiUrl.trim()
    if (formValues.embeddingApiKey?.trim())
      payload.embedding_api_key = formValues.embeddingApiKey.trim()
    if (formValues.embeddingModel?.trim())
      payload.embedding_model = formValues.embeddingModel.trim()
    const dim = Number.parseInt(String(formValues.embeddingDimension ?? ''), 10)
    if (!Number.isNaN(dim) && dim > 0)
      payload.embedding_dimension = dim

    await setupRag(payload)
    emit('done')
  }
  catch (e: unknown) {
    submitError.value = e instanceof Error ? e.message : t('setup.rag.error.default')
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
        <span class="icon-[lucide--database] text-3xl text-primary" />
      </div>
      <h1 class="text-2xl font-bold text-foreground mb-1">
        {{ t('setup.rag.title') }}
      </h1>
      <p class="text-sm text-muted-foreground">
        {{ t('setup.rag.subtitle') }}
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
      <FormField v-slot="{ componentField }" name="qdrantUrl">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.rag.fields.qdrantUrl') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="text"
                :placeholder="t('setup.rag.fields.qdrantUrlPlaceholder')"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <FormField v-slot="{ componentField }" name="qdrantApiKey">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.rag.fields.qdrantApiKey') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key-round] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="password"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <FormField v-slot="{ componentField }" name="embeddingApiUrl">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.rag.fields.embeddingApiUrl') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--link] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="text"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <FormField v-slot="{ componentField }" name="embeddingApiKey">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.rag.fields.embeddingApiKey') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key-round] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="password"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <div class="grid grid-cols-2 gap-3">
        <FormField v-slot="{ componentField }" name="embeddingModel">
          <FormItem>
            <FormLabel class="text-foreground/80 text-sm font-medium">
              {{ t('setup.rag.fields.embeddingModel') }}
            </FormLabel>
            <FormControl>
              <Input type="text" autocomplete="off" v-bind="componentField" />
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>

        <FormField v-slot="{ componentField }" name="embeddingDimension">
          <FormItem>
            <FormLabel class="text-foreground/80 text-sm font-medium">
              {{ t('setup.rag.fields.embeddingDimension') }}
            </FormLabel>
            <FormControl>
              <Input type="number" inputmode="numeric" autocomplete="off" v-bind="componentField" />
            </FormControl>
            <FormMessage />
          </FormItem>
        </FormField>
      </div>

      <Button
        type="submit"
        class="w-full h-10 text-sm font-semibold mt-2"
        :disabled="isSubmitting"
      >
        <template v-if="isSubmitting">
          <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
          {{ t('setup.rag.saving') }}
        </template>
        <template v-else>
          <span class="icon-[lucide--check] mr-2" />
          {{ t('setup.rag.cta') }}
        </template>
      </Button>

      <button
        type="button"
        class="w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors pt-1"
        :disabled="isSubmitting"
        @click="emit('skip')"
      >
        {{ t('setup.rag.skip') }}
      </button>
    </form>
  </div>
</template>
