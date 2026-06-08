<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { ref } from 'vue'
import * as z from 'zod'
import { getSetupStatus } from '~/api/setup'
import { Button } from '~/components/ui/button'
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '~/components/ui/form'
import { Input } from '~/components/ui/input'
import { useAuthStore } from '~/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()

const setupError = ref<string | null>(null)
const isSubmitting = ref(false)

const formSchema = toTypedSchema(z.object({
  username: z.string().min(1, '请输入用户名').max(150, '用户名过长'),
  password: z.string().min(6, '密码至少 6 位'),
  confirmPassword: z.string().min(1, '请确认密码'),
}).refine(data => data.password === data.confirmPassword, {
  message: '两次输入的密码不一致',
  path: ['confirmPassword'],
}))

const { handleSubmit } = useForm({
  validationSchema: formSchema,
  initialValues: {
    username: 'admin',
    password: '',
    confirmPassword: '',
  },
})

const onSubmit = handleSubmit(async (values) => {
  setupError.value = null
  isSubmitting.value = true
  try {
    const response = await fetch('/api/auth/setup/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username: values.username,
        password: values.password,
        display_name: '系统管理员',
      }),
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || '设置失败')
    }

    // 设置成功，更新 setup 状态，跳转登录页
    authStore.needsSetup = false
    authStore.setupStatusChecked = true
    router.push('/login')
  }
  catch (e: unknown) {
    setupError.value = e instanceof Error ? e.message : '设置失败，请重试'
  }
  finally {
    isSubmitting.value = false
  }
})

// 检测是否需要 setup（复用 API 工具函数，遵守 VITE_API_URL 配置）
onMounted(async () => {
  try {
    const setupStatus = await getSetupStatus()
    if (!setupStatus.needs_setup) {
      router.push('/login')
    }
  }
  catch {
    setupError.value = t('setup.error.connection')
  }
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center relative overflow-hidden">
    <div class="absolute inset-0 bg-mesh-gradient" />
    <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/4" />
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] bg-cyan-500/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/4" />

    <div class="relative z-10 w-full max-w-md mx-4">
      <div class="bg-card/70 backdrop-blur-xl rounded-2xl border border-border/50 shadow-glass p-8">
        <div class="mb-6 text-center">
          <div class="inline-flex items-center justify-center p-3 mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
            <span class="icon-[lucide--settings] text-3xl text-primary" />
          </div>
          <h1 class="text-2xl font-bold text-foreground mb-1">
            {{ t('setup.title') }}
          </h1>
          <p class="text-sm text-muted-foreground">
            {{ t('setup.subtitle') }}
          </p>
        </div>

        <div
          v-if="setupError"
          class="flex items-center gap-2.5 p-3 rounded-xl bg-destructive/8 border border-destructive/15 text-destructive mb-5"
        >
          <span class="icon-[lucide--alert-circle] text-base flex-shrink-0" />
          <span class="text-sm">{{ setupError }}</span>
        </div>

        <form class="space-y-4" @submit="onSubmit">
          <FormField v-slot="{ componentField }" name="username">
            <FormItem>
              <FormLabel class="text-foreground/80 text-sm font-medium">
                {{ t('setup.fields.username') }}
              </FormLabel>
              <FormControl>
                <div class="relative group">
                  <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--user] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
                  <Input
                    type="text"
                    placeholder="admin"
                    autocomplete="username"
                    class="pl-9"
                    v-bind="componentField"
                  />
                </div>
              </FormControl>
              <FormMessage />
            </FormItem>
          </FormField>

          <FormField v-slot="{ componentField }" name="password">
            <FormItem>
              <FormLabel class="text-foreground/80 text-sm font-medium">
                {{ t('setup.fields.password') }}
              </FormLabel>
              <FormControl>
                <div class="relative group">
                  <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
                  <Input
                    type="password"
                    placeholder="至少 6 位"
                    autocomplete="new-password"
                    class="pl-9"
                    v-bind="componentField"
                  />
                </div>
              </FormControl>
              <FormMessage />
            </FormItem>
          </FormField>

          <FormField v-slot="{ componentField }" name="confirmPassword">
            <FormItem>
              <FormLabel class="text-foreground/80 text-sm font-medium">
                {{ t('setup.fields.confirmPassword') }}
              </FormLabel>
              <FormControl>
                <div class="relative group">
                  <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
                  <Input
                    type="password"
                    placeholder="再次输入密码"
                    autocomplete="new-password"
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
              {{ t('setup.submitting') }}
            </template>
            <template v-else>
              <span class="icon-[lucide--shield-check] mr-2" />
              {{ t('setup.cta') }}
            </template>
          </Button>
        </form>
      </div>
    </div>
  </div>
</template>

<route lang="yaml">
meta:
  layout: false
</route>
