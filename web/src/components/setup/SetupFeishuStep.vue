<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { ref } from 'vue'
import * as z from 'zod'
import { setupFeishu } from '~/api/setup'
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
  appId: z.string().min(1, t('setup.feishu.validation.appIdRequired')),
  appSecret: z.string().min(1, t('setup.feishu.validation.appSecretRequired')),
}))

const { handleSubmit } = useForm({
  validationSchema: formSchema,
  initialValues: { appId: '', appSecret: '' },
})

const onSubmit = handleSubmit(async (formValues) => {
  submitError.value = null
  isSubmitting.value = true
  try {
    await setupFeishu({
      app_id: formValues.appId,
      app_secret: formValues.appSecret,
    })
    emit('done')
  }
  catch (e: unknown) {
    submitError.value = e instanceof Error ? e.message : t('setup.feishu.error.default')
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
        <span class="icon-[lucide--message-square] text-3xl text-primary" />
      </div>
      <h1 class="text-2xl font-bold text-foreground mb-1">
        {{ t('setup.feishu.title') }}
      </h1>
      <p class="text-sm text-muted-foreground">
        {{ t('setup.feishu.subtitle') }}
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
      <FormField v-slot="{ componentField }" name="appId">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.feishu.fields.appId') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--app-window] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="text"
                :placeholder="t('setup.feishu.fields.appIdPlaceholder')"
                autocomplete="off"
                class="pl-9"
                v-bind="componentField"
              />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      </FormField>

      <FormField v-slot="{ componentField }" name="appSecret">
        <FormItem>
          <FormLabel class="text-foreground/80 text-sm font-medium">
            {{ t('setup.feishu.fields.appSecret') }}
          </FormLabel>
          <FormControl>
            <div class="relative group">
              <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key-round] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
              <Input
                type="password"
                :placeholder="t('setup.feishu.fields.appSecretPlaceholder')"
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
          {{ t('setup.feishu.saving') }}
        </template>
        <template v-else>
          <span class="icon-[lucide--check] mr-2" />
          {{ t('setup.feishu.cta') }}
        </template>
      </Button>

      <button
        type="button"
        class="w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors pt-1"
        :disabled="isSubmitting"
        @click="emit('skip')"
      >
        {{ t('setup.feishu.skip') }}
      </button>
    </form>
  </div>
</template>
