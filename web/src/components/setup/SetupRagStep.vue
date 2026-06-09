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

const props = withDefaults(
  defineProps<{ showPrev?: boolean, qdrantBundled?: boolean, qdrantManagedUrl?: string }>(),
  { showPrev: false, qdrantBundled: false, qdrantManagedUrl: '' },
)
// 托管时锁定的 Qdrant 地址：优先用后端回传的真实 env 地址，回退到 compose 内置默认
const lockedQdrantUrl = props.qdrantManagedUrl || 'http://qdrant:6333'
const emit = defineEmits<{ done: [], skip: [], prev: [] }>()
const { t } = useI18n()

const DOUBAO_URL = 'https://www.volcengine.com/product/doubao'
const QIANWEN_URL = 'https://dashscope.console.aliyun.com/'

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
    qdrantUrl: props.qdrantBundled ? lockedQdrantUrl : 'http://qdrant:6333',
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
    // 托管 Qdrant 时强制使用 env 锁定地址，忽略任何被改动的输入值（server 也以 env 为准）
    const qdrantUrl = props.qdrantBundled ? lockedQdrantUrl : formValues.qdrantUrl
    const payload: SetupRagRequest = { qdrant_url: qdrantUrl }
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

    <!-- 用途说明：告诉用户向量检索是干嘛的 -->
    <p class="flex items-start gap-1.5 mb-3 text-xs text-muted-foreground">
      <span class="icon-[lucide--info] text-sm flex-shrink-0 mt-0.5" />
      <span>{{ t('setup.rag.about') }}</span>
    </p>

    <!-- Embedding 服务引导：没有可去豆包 / 通义千问 注册购买 -->
    <p class="flex items-start gap-1.5 mb-4 text-xs text-muted-foreground">
      <span class="icon-[lucide--sparkles] text-sm flex-shrink-0 mt-0.5" />
      <span>
        {{ t('setup.rag.embeddingGuide') }}
        <a
          :href="DOUBAO_URL"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-0.5 text-primary hover:underline"
        >
          {{ t('setup.rag.doubaoLink') }}
          <span class="icon-[lucide--external-link] text-[0.7rem]" />
        </a>
        <span class="mx-1">/</span>
        <a
          :href="QIANWEN_URL"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-0.5 text-primary hover:underline"
        >
          {{ t('setup.rag.qianwenLink') }}
          <span class="icon-[lucide--external-link] text-[0.7rem]" />
        </a>
      </span>
    </p>

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
                :readonly="props.qdrantBundled"
                :class="props.qdrantBundled ? 'opacity-70 cursor-not-allowed' : ''"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <!-- 内置 Qdrant 时锁定地址：不允许更改，使用 docker compose 内置实例 -->
          <p
            v-if="props.qdrantBundled"
            class="flex items-center gap-1.5 text-xs text-muted-foreground"
          >
            <span class="icon-[lucide--lock] text-[0.7rem] flex-shrink-0" />
            {{ t('setup.rag.qdrantBundledNote') }}
          </p>
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

      <!-- 导航：上一步 / 跳过 / 保存并完成 -->
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
          {{ t('setup.rag.skip') }}
        </Button>
        <Button
          type="submit"
          class="h-10 flex-1 text-sm font-semibold"
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
      </div>
    </form>
  </div>
</template>
