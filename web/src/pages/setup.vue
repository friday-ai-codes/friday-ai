<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { ref } from 'vue'
import * as z from 'zod'
import { getSetupStatus } from '~/api/setup'
import SetupFeishuStep from '~/components/setup/SetupFeishuStep.vue'
import SetupProviderStep from '~/components/setup/SetupProviderStep.vue'
import SetupRagStep from '~/components/setup/SetupRagStep.vue'
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

// 多步向导：管理员账户 → AI 供应商（Phase 3）→ 飞书集成 → 向量检索（Phase 4）
type SetupStep = 'admin' | 'provider' | 'feishu' | 'rag'
const STEPS: SetupStep[] = ['admin', 'provider', 'feishu', 'rag']
const step = ref<SetupStep>('admin')
const currentStepIndex = computed(() => STEPS.indexOf(step.value))
const setupError = ref<string | null>(null)
const isSubmitting = ref(false)
// 是否随部署内置 Qdrant（docker compose 已启动）：为 true 时向量检索步骤锁定 Qdrant 地址
const qdrantBundled = ref(false)

const formSchema = toTypedSchema(z.object({
  username: z.string().min(1, t('setup.validation.usernameRequired')).max(150, '用户名过长'),
  password: z.string()
    .min(8, t('setup.validation.passwordMin'))
    .refine(v => !/^\d+$/.test(v), t('setup.validation.passwordNumeric')),
  confirmPassword: z.string().min(1, t('setup.fields.confirmPassword')),
}).refine(data => data.password === data.confirmPassword, {
  message: t('setup.validation.passwordMismatch'),
  path: ['confirmPassword'],
}))

const { handleSubmit, values } = useForm({
  validationSchema: formSchema,
  initialValues: {
    username: 'admin',
    password: '',
    confirmPassword: '',
  },
})

// 密码强度（仅 UX 提示，最终以后端 Django 校验器为准）：
// 满足项数（长度≥8 / 含字母 / 含数字 / 含符号或长度≥12）→ 弱(0-1)/中(2-3)/强(4)
const passwordStrength = computed(() => {
  const pwd = values.password ?? ''
  if (!pwd)
    return null
  let score = 0
  if (pwd.length >= 8)
    score++
  if (/[a-z]/i.test(pwd))
    score++
  if (/\d/.test(pwd))
    score++
  if (/[^a-z0-9]/i.test(pwd) || pwd.length >= 12)
    score++
  const level = score <= 1 ? 'weak' : score <= 3 ? 'medium' : 'strong'
  const meta = {
    weak: { filled: 1, bar: 'bg-destructive', text: 'text-destructive' },
    medium: { filled: 2, bar: 'bg-amber-500', text: 'text-amber-500' },
    strong: { filled: 3, bar: 'bg-primary', text: 'text-primary' },
  } as const
  return { level, ...meta[level] }
})

// 从后端 400 响应中提取字段级中文错误（password/username）
function firstFieldError(data: Record<string, unknown> | null): string | null {
  if (!data || typeof data !== 'object')
    return null
  for (const key of ['password', 'username', 'confirmPassword']) {
    const v = data[key]
    if (Array.isArray(v) && v.length)
      return String(v[0])
    if (typeof v === 'string')
      return v
  }
  return null
}

const onSubmit = handleSubmit(async (formValues) => {
  setupError.value = null
  isSubmitting.value = true
  try {
    // 保持原始 fetch（不走 api/client.ts），避免 403/401 触发全局 auth:forbidden/logout 重定向
    const response = await fetch('/api/auth/setup/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username: formValues.username,
        password: formValues.password,
        display_name: '系统管理员',
      }),
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(firstFieldError(data) || data.detail || t('setup.error.default'))
    }

    // 后端已下发 cookie-JWT 会话：写入前端会话状态（ADMIN-03）。
    // Phase 3：管理员创建成功后不再直达首页，而是原地进入「AI 供应商」步骤
    // （组件内部状态切换，不触发 /setup 路由导航，避免改动 Phase 1 门禁守卫）。
    authStore.applySetupSession(data.user)
    try {
      await authStore.fetchMe()
    }
    catch {
      // 静默忽略扩展信息获取失败，不影响进入系统（与 login() 一致）
    }
    step.value = 'provider'
  }
  catch (e: unknown) {
    setupError.value = e instanceof Error ? e.message : t('setup.error.default')
  }
  finally {
    isSubmitting.value = false
  }
})

// 检测是否需要 setup（复用 API 工具函数，遵守 VITE_API_URL 配置）
onMounted(async () => {
  try {
    const setupStatus = await getSetupStatus()
    qdrantBundled.value = Boolean(setupStatus.qdrant_bundled)
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

    <div
      class="relative z-10 w-full mx-4 transition-all"
      :class="step === 'admin' ? 'max-w-md' : 'max-w-lg'"
    >
      <div class="bg-card/70 backdrop-blur-xl rounded-2xl border border-border/50 shadow-glass p-8">
        <!-- 步骤指示：N 圆点 + 文字进度（第 current / total 步） -->
        <div class="mb-6 flex flex-col items-center gap-2">
          <div class="flex items-center gap-1.5">
            <template v-for="(s, i) in STEPS" :key="s">
              <span
                class="h-2 rounded-full transition-all"
                :class="i === currentStepIndex
                  ? 'w-6 bg-primary'
                  : i < currentStepIndex ? 'w-2 bg-primary/50' : 'w-2 bg-border'"
              />
            </template>
          </div>
          <p class="text-xs text-muted-foreground">
            {{ t('setup.steps.indicator', { current: currentStepIndex + 1, total: STEPS.length }) }}
            · {{ t(`setup.steps.${step}`) }}
          </p>
        </div>

        <!-- 步骤 2：AI 供应商配置（Phase 3）→ 完成/跳过推进到飞书集成 -->
        <SetupProviderStep
          v-if="step === 'provider'"
          @done="step = 'feishu'"
          @skip="step = 'feishu'"
        />

        <!-- 步骤 3：飞书集成（Phase 4，可跳过） -->
        <SetupFeishuStep
          v-else-if="step === 'feishu'"
          show-prev
          @done="step = 'rag'"
          @skip="step = 'rag'"
          @prev="step = 'provider'"
        />

        <!-- 步骤 4：向量检索（Phase 4，可跳过，末步进入首页） -->
        <SetupRagStep
          v-else-if="step === 'rag'"
          show-prev
          :qdrant-bundled="qdrantBundled"
          @done="router.push('/')"
          @skip="router.push('/')"
          @prev="step = 'feishu'"
        />

        <!-- 步骤 1：管理员账户（Phase 1/2） -->
        <template v-else>
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
                      :placeholder="t('setup.fields.passwordPlaceholder')"
                      autocomplete="new-password"
                      class="pl-9"
                      v-bind="componentField"
                    />
                  </div>
                </FormControl>
                <div v-if="passwordStrength" class="space-y-1.5 pt-1">
                  <div class="flex gap-1">
                    <span
                      v-for="i in 3"
                      :key="i"
                      class="h-1.5 flex-1 rounded-full transition-colors"
                      :class="i <= passwordStrength.filled ? passwordStrength.bar : 'bg-border'"
                    />
                  </div>
                  <p class="text-xs" :class="passwordStrength.text">
                    {{ t('setup.strength.label') }}：{{ t(`setup.strength.${passwordStrength.level}`) }}
                  </p>
                </div>
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
        </template>
      </div>
    </div>
  </div>
</template>

<route lang="yaml">
meta:
  layout: false
</route>
