<script setup lang="ts">
/**
 * OIDC 回调处理页面
 * 后端已通过 HTTP-only Cookie 设置 token，前端直接获取用户信息后跳转
 */
import { useAuthStore } from '~/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const error = ref<string | null>(null)
const processing = ref(true)

onMounted(async () => {
  const oidcError = route.query.error as string
  const redirectPath = (route.query.redirect as string) || '/'

  if (oidcError) {
    error.value = decodeURIComponent(oidcError)
    processing.value = false
    return
  }

  try {
    // Cookie 已由后端设置，直接获取用户信息
    await authStore.fetchCurrentUser()
    authStore.isAuthenticated = true
    // 获取空间成员信息，确保权限系统立即可用
    await authStore.fetchMe()
    // 跳转到目标页面
    router.replace(redirectPath)
  }
  catch {
    error.value = '登录处理失败，请重试'
    processing.value = false
  }
})

function goToLogin() {
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
    <!-- 背景装饰 -->
    <div class="absolute inset-0 -z-10">
      <div class="absolute -top-40 -right-40 w-96 h-96 bg-primary/10 rounded-full blur-3xl" />
      <div class="absolute -bottom-40 -left-40 w-96 h-96 bg-gradient-to-tr from-secondary/40 to-primary/20 rounded-full blur-3xl" />
    </div>

    <div class="w-full max-w-md mx-4">
      <div class="relative">
        <div class="relative bg-card/80 backdrop-blur-xl rounded-2xl border border-border/50 shadow-2xl shadow-primary/5 p-8 text-center">
          <!-- 处理中 -->
          <template v-if="processing">
            <div class="inline-flex items-center justify-center p-3 mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/30 to-primary/10 border border-primary/10">
              <span class="icon-[lucide--loader-circle] text-4xl text-primary animate-spin" />
            </div>
            <h2 class="text-xl font-semibold mb-2">
              OIDC 登录中...
            </h2>
            <p class="text-sm text-muted-foreground">
              正在完成认证，请稍候
            </p>
          </template>

          <!-- 错误 -->
          <template v-else-if="error">
            <div class="inline-flex items-center justify-center p-3 mb-4 rounded-2xl bg-destructive/10 border border-destructive/20">
              <span class="icon-[lucide--alert-circle] text-4xl text-destructive" />
            </div>
            <h2 class="text-xl font-semibold mb-2">
              登录失败
            </h2>
            <p class="text-sm text-muted-foreground mb-6">
              {{ error }}
            </p>
            <button
              class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              @click="goToLogin"
            >
              <span class="icon-[lucide--arrow-left]" />
              返回登录
            </button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<route lang="yaml">
meta:
  layout: false
</route>
