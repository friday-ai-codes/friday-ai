<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
/**
 * 登录页面
 */
import { useForm } from 'vee-validate'
import * as z from 'zod'
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
// 表单验证 schema
const formSchema = toTypedSchema(z.object({
 username: z.string.min(1, '请输入用户名'),
 password: z.string.min(1, '请输入密码'),
}))
const { handleSubmit, isSubmitting } = useForm({
 validationSchema: formSchema,
})
const loginError = ref<string | null>(null)
// 处理登录
const onSubmit = handleSubmit(async (values) => {
 loginError.value = null
 try {
 const result = await authStore.login(values.username, values.password)
 // 检查是否需要强制修改密码
 if (result.mustChangePassword) {
 router.push('/force-change-password')
 return
 }
 // 登录成功，跳转到原页面或首页
 const redirect = route.query.redirect as string || '/'
 router.push(redirect)
 }
 catch (e) {
 loginError.value = e instanceof Error ? e.message: '登录失败，请重试'
 }
})
// 如果已登录，跳转首页
onMounted( => {
 if (authStore.isAuthenticated) {
 router.push('/')
 }
})
</script>
<template>
 <div class="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10">
 <div class="absolute -top-40 -right-40 w-96 bg-gradient-to-br from-primary/30 to-secondary/50 rounded-full blur-3xl" />
 <div class="absolute -bottom-40 -left-40 w-96 bg-gradient-to-tr from-secondary/40 to-primary/20 rounded-full blur-3xl" />
 <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-gradient-to-r from-primary/5 to-secondary/10 rounded-full blur-3xl" />
 </div>
 <!-- 登录卡片 -->
 <div class="w-full max-w-md mx-4">
 <div class="relative">
 <!-- 卡片光晕 -->
 <div class="absolute -inset-1 bg-gradient-to-r from-primary/20 via-secondary/30 to-primary/20 rounded-3xl blur-xl opacity-70" />
 <!-- 卡片主体 -->
 <div class="relative bg-card/80 backdrop-blur-xl rounded-2xl border border-border/50 shadow-2xl shadow-primary/5 ">
 <!-- Logo -->
 <div class="text-center mb-8">
 <div class="inline-flex items-center justify-center mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/30 to-primary/10 border border-primary/10">
 <span class="icon-[lucide--bot] text-4xl text-primary" />
 </div>
 <h1 class="text-2xl font-bold bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent">
 Friday AI
 </h1>
 </div>
 <!-- 登录表单 -->
 <form class="space-y-5" @submit="onSubmit">
 <!-- 错误提示 -->
 <div
 v-if="loginError"
 class="flex items-center gap-3 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive"
 >
 <span class="icon-[lucide--alert-circle] text-lg flex-shrink-0" />
 <span class="text-sm">{{ loginError }}</span>
 </div>
 <!-- 用户名 -->
 <FormField v-slot="{ componentField }" name="username">
 <FormItem>
 <FormLabel class="text-foreground/80">
 用户名
 </FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--user] text-muted-foreground" />
 <Input
 type="text"
 placeholder="请输入用户名"
 autocomplete="username"
 class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50 focus:ring-primary/20"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 密码 -->
 <FormField v-slot="{ componentField }" name="password">
 <FormItem>
 <FormLabel class="text-foreground/80">
 密码
 </FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请输入密码"
 autocomplete="current-password"
 class="pl-10 bg-muted/30 border-border/50 focus:border-primary/50 focus:ring-primary/20"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 登录按钮 -->
 <Button
 type="submit"
 class="w-full text-base font-medium group relative overflow-hidden":disabled="isSubmitting"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
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
 </div>
 </div>
 <!-- 底部版权 -->
 <p class="text-center text-sm text-muted-foreground/60 mt-8">
 © {{ new Date.getFullYear }} Friday AI. All rights reserved.
 </p>
 </div>
 </div>
</template>
<route lang="yaml">
meta:
 layout: false
</route>
