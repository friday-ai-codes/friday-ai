<script setup lang="ts">
import type { OIDCProviderPublic } from '~/types'
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import * as z from 'zod'
import { getAuthorizeUrl, getPublicProviders } from '~/api/oidc'
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
const router = useRouter
const route = useRoute
const authStore = useAuthStore
const formSchema = toTypedSchema(z.object({
 username: z.string.min(1, '请输入用户名'),
 password: z.string.min(1, '请输入密码'),
}))
const { handleSubmit, isSubmitting } = useForm({
 validationSchema: formSchema,
 initialValues: {
 username: '',
 password: '',
 },
})
const loginError = ref<string | null>(null)
const oidcProviders = ref<OIDCProviderPublic>
const oidcLoading = ref(false)
const showAdminLogin = ref(false)
const hasOIDC = computed( => oidcProviders.value.length > 0)
const showAdminForm = computed( => !hasOIDC.value || showAdminLogin.value)
const onSubmit = handleSubmit(async (values) => {
 loginError.value = null
 try {
 const result = await authStore.login(values.username, values.password)
 if (result.mustChangePassword) {
 router.push('/force-change-password')
 return
 }
 const redirect = route.query.redirect as string || '/'
 router.push(redirect)
 }
 catch (e: unknown) {
 loginError.value = e instanceof Error ? e.message: '登录失败，请重试'
 }
})
async function onOIDCLogin(provider: OIDCProviderPublic) {
 oidcLoading.value = true
 try {
 const redirectUri = (route.query.redirect as string) || '/'
 const controller = new AbortController
 const timeout = setTimeout( => controller.abort, 10_000)
 try {
 const result = await getAuthorizeUrl(provider.id, redirectUri)
 clearTimeout(timeout)
 window.location.href = result.authorize_url
 }
 catch (e: unknown) {
 clearTimeout(timeout)
 throw e
 }
 }
 catch (e: unknown) {
 if (e instanceof DOMException && e.name === 'AbortError') {
 loginError.value = '认证服务暂时不可用，请稍后重试'
 }
 else if (e instanceof TypeError && (e.message.includes('fetch') || e.message.includes('network'))) {
 loginError.value = '认证服务暂时不可用，请稍后重试'
 }
 else {
 loginError.value = 'OIDC 登录初始化失败，请重试'
 }
 oidcLoading.value = false
 }
}
onMounted(async => {
 if (authStore.isAuthenticated) {
 router.push('/')
 return
 }
 const oidcError = route.query.oidc_error as string
 if (oidcError) {
 loginError.value = decodeURIComponent(oidcError)
 }
 try {
 oidcProviders.value = await getPublicProviders
 }
 catch {
 // 静默忽略
 }
})
const features = [
 { icon: 'icon-[lucide--bot]', text: 'AI 驱动的智能开发助手' },
 { icon: 'icon-[lucide--git-branch]', text: '自动化代码审查与分支管理' },
 { icon: 'icon-[lucide--workflow]', text: '可视化工作流编排' },
 { icon: 'icon-[lucide--shield-check]', text: '企业级安全与权限控制' },
]
</script>
<template>
 <div class="min-h-screen flex">
 <!-- 左侧品牌区 -->
 <div class="hidden lg:flex lg:w-1/2 xl:w-[55%] relative flex-col justify-between overflow-hidden bg-slate-900">
 <!-- 背景装饰 -->
 <div class="absolute inset-0">
 <!-- 网格纹理 -->
 <div
 class="absolute inset-0 opacity-[0.03]"
 style="background-image: linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px); background-size: 48px 48px;"
 />
 <!-- subtle radial glow -->
 <div class="absolute -top-1/4 -right-1/4 w-[600px] h-[600px] rounded-full bg-teal-500/10 blur-3xl" />
 <div class="absolute -bottom-1/4 -left-1/4 w-[500px] h-[500px] rounded-full bg-cyan-500/5 blur-3xl" />
 </div>
 <!-- 顶部 Logo -->
 <RouterLink to="/" class="relative z-10 flex items-center gap-3 group">
 <img
 src="/logo-mark-dark.svg"
 alt="Friday"
 class="w-10 drop-shadow-[0_4px_16px_rgba(20,184,166,0.35)] transition-transform duration-200 group-hover:scale-105"
 >
 <img src="/logo-wordmark-dark.svg" alt="friday" class=" w-auto">
 </RouterLink>
 <!-- 中间内容 -->
 <div class="relative z-10 max-w-md">
 <h2 class="text-4xl font-bold text-white leading-tight mb-4 animate-fade-in">
 让 AI 成为您的<br>
 <span class="bg-gradient-to-r from-teal-300 to-cyan-300 bg-clip-text text-transparent">开发伙伴</span>
 </h2>
 <p class="text-slate-400 text-lg mb-10 leading-relaxed">
 智能代码审查、自动化工作流、AI 辅助编程——Friday AI 帮助团队更高效地构建软件。
 </p>
 <!-- Feature 列表 -->
 <div class="space-y-4">
 <div
 v-for="(feature, i) in features":key="i"
 class="flex items-center gap-3 text-slate-300 animate-slide-in-right":style="{ animationDelay: `${200 + i * 100}ms`, animationFillMode: 'both' }"
 >
 <div class="w-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center flex-shrink-0">
 <span:class="`${feature.icon} text-sm text-teal-400`" />
 </div>
 <span class="text-sm">{{ feature.text }}</span>
 </div>
 </div>
 </div>
 <!-- 底部 -->
 <div class="relative z-10 text-slate-500 text-sm">
 &copy; {{ new Date.getFullYear }} Friday AI. All rights reserved.
 </div>
 </div>
 <!-- 右侧表单区 -->
 <div class="flex-1 flex items-center justify-center relative overflow-hidden">
 <!-- 背景层次 -->
 <div class="absolute inset-0 bg-mesh-gradient" />
 <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/4" />
 <div class="absolute bottom-0 left-0 w-[400px] h-[400px] bg-cyan-500/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/4" />
 <!-- 移动端顶部 Logo -->
 <RouterLink to="/" class="lg:hidden absolute top-6 left-6 flex items-center gap-2 z-10 group">
 <img
 src="/logo-mark.svg"
 alt="Friday"
 class="w-8 transition-transform duration-200 group-hover:scale-105"
 >
 <img src="/logo-wordmark.svg" alt="friday" class=" w-auto">
 </RouterLink>
 <!-- 登录卡片 -->
 <div class="relative z-10 w-full max-w-sm mx-4">
 <div class="bg-card/70 backdrop-blur-xl rounded-2xl border border-border/50 shadow-glass animate-scale-in">
 <!-- 标题 -->
 <div class="mb-8">
 <h1 class="text-2xl font-bold text-foreground mb-1">
 欢迎回来
 </h1>
 <p class="text-sm text-muted-foreground">
 {{ hasOIDC && !showAdminLogin ? '使用企业账号登录 Friday AI': '登录您的 Friday AI 账户' }}
 </p>
 </div>
 <!-- 错误提示 -->
 <Transition
 enter-active-class="transition-all duration-200 ease-out"
 enter-from-class="opacity-0 -translate-y-1"
 enter-to-class="opacity-100 translate-y-0"
 leave-active-class="transition-all duration-150 ease-in"
 leave-from-class="opacity-100 translate-y-0"
 leave-to-class="opacity-0 -translate-y-1"
 >
 <div
 v-if="loginError"
 class="flex items-center gap-2.5 rounded-xl bg-destructive/8 border border-destructive/15 text-destructive mb-5"
 >
 <span class="icon-[lucide--alert-circle] text-base flex-shrink-0" />
 <span class="text-sm">{{ loginError }}</span>
 </div>
 </Transition>
 <!-- OIDC 登录（主要入口，仅在配置了 Provider 且未切换到管理员登录时显示） -->
 <div v-if="hasOIDC && !showAdminLogin" class="space-y-2.5">
 <Button
 v-for="provider in oidcProviders":key="provider.id"
 class="w-full text-sm font-semibold":disabled="oidcLoading"
 @click="onOIDCLogin(provider)"
 >
 <template v-if="oidcLoading">
 <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 跳转中...
 </template>
 <template v-else>
 <span class="icon-[lucide--shield-check] mr-2" />
 使用 {{ provider.name }} 登录
 </template>
 </Button>
 </div>
 <!-- 管理员账号密码登录表单 -->
 <form v-if="showAdminForm" class="space-y-4" @submit="onSubmit">
 <FormField v-slot="{ componentField }" name="username">
 <FormItem>
 <FormLabel class="text-foreground/80 text-sm font-medium">
 用户名
 </FormLabel>
 <FormControl>
 <div class="relative group">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--user] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
 <Input
 type="text"
 placeholder="请输入用户名"
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
 密码
 </FormLabel>
 <FormControl>
 <div class="relative group">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground text-sm transition-colors group-focus-within:text-primary" />
 <Input
 type="password"
 placeholder="请输入密码"
 autocomplete="current-password"
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
 class="w-full text-sm font-semibold mt-2":disabled="isSubmitting"
 >
 <template v-if="isSubmitting">
 <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 登录中...
 </template>
 <template v-else>
 <span class="icon-[lucide--log-in] mr-2" />
 登录
 </template>
 </Button>
 </form>
 <!-- 切换登录方式（仅在配了 OIDC 时显示） -->
 <div v-if="hasOIDC" class="mt-6">
 <div class="flex items-center gap-3 mb-3">
 <div class="flex-1 h-px bg-border/40" />
 <span class="text-xs text-muted-foreground">其他方式</span>
 <div class="flex-1 h-px bg-border/40" />
 </div>
 <button
 type="button"
 class="w-full text-center text-xs text-muted-foreground hover:text-foreground transition-colors"
 @click="showAdminLogin = !showAdminLogin"
 >
 <template v-if="showAdminLogin">
 <span class="icon-[lucide--arrow-left] mr-1 align-[-2px]" />
 返回企业账号登录
 </template>
 <template v-else>
 <span class="icon-[lucide--key] mr-1 align-[-2px]" />
 管理员账号登录
 </template>
 </button>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
<route lang="yaml">
meta:
 layout: false
</route>
