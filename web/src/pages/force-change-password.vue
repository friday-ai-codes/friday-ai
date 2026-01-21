<script setup lang="ts">
/**
 * 强制修改密码页面
 * 首次登录或密码重置后必须修改密码
 */
import { useForm } from 'vee-validate'
import { toTypedSchema } from '@vee-validate/zod'
import * as z from 'zod'
import { toast } from 'vue-sonner'
import { useAuthStore } from '~/stores/auth'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
 FormControl,
 FormField,
 FormItem,
 FormLabel,
 FormMessage,
} from '~/components/ui/form'
const router = useRouter
const authStore = useAuthStore
// 表单验证 schema
const formSchema = toTypedSchema(z.object({
 new_password: z.string.min(6, '密码至少 6 位'),
 confirm_password: z.string.min(6, '请确认密码'),
}).refine(data => data.new_password === data.confirm_password, {
 message: '两次输入的密码不一致',
 path: ['confirm_password'],
}))
const { handleSubmit, isSubmitting } = useForm({
 validationSchema: formSchema,
})
const submitError = ref<string | null>(null)
// 处理提交
const onSubmit = handleSubmit(async (values) => {
 submitError.value = null
 try {
 await authStore.forceChangePassword({ new_password: values.new_password })
 toast.success('密码修改成功，请重新登录')
 // 清除登录状态，要求重新登录
 await authStore.logout
 router.push('/login')
 } catch (e) {
 submitError.value = e instanceof Error ? e.message: '修改密码失败，请重试'
 }
})
// 如果不需要修改密码，跳转首页
onMounted( => {
 if (!authStore.isAuthenticated) {
 router.push('/login')
 } else if (!authStore.mustChangePassword) {
 router.push('/')
 }
})
</script>
<template>
 <div class="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10">
 <div class="absolute -top-40 -right-40 w-96 bg-gradient-to-br from-amber-500/20 to-orange-500/30 rounded-full blur-3xl" />
 <div class="absolute -bottom-40 -left-40 w-96 bg-gradient-to-tr from-secondary/40 to-primary/20 rounded-full blur-3xl" />
 <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-gradient-to-r from-primary/5 to-secondary/10 rounded-full blur-3xl" />
 </div>
 <!-- 修改密码卡片 -->
 <div class="w-full max-w-md mx-4">
 <div class="relative">
 <!-- 卡片光晕 -->
 <div class="absolute -inset-1 bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-amber-500/20 rounded-3xl blur-xl opacity-70" />
 <!-- 卡片主体 -->
 <div class="relative bg-card/80 backdrop-blur-xl rounded-2xl border border-border/50 shadow-2xl shadow-amber-500/5 ">
 <!-- Logo -->
 <div class="text-center mb-8">
 <div class="inline-flex items-center justify-center mb-4 rounded-2xl bg-gradient-to-br from-amber-500/10 via-orange-500/20 to-amber-500/10 border border-amber-500/20">
 <span class="icon-[lucide--shield-check] text-4xl text-amber-500" />
 </div>
 <h1 class="text-2xl font-bold">修改密码</h1>
 <p class="text-muted-foreground mt-2">
 为了账户安全，请设置一个新密码
 </p>
 </div>
 <!-- 表单 -->
 <form class="space-y-5" @submit="onSubmit">
 <!-- 错误提示 -->
 <div
 v-if="submitError"
 class="flex items-center gap-3 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive"
 >
 <span class="icon-[lucide--alert-circle] text-lg flex-shrink-0" />
 <span class="text-sm">{{ submitError }}</span>
 </div>
 <!-- 警告提示 -->
 <div class="flex items-center gap-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700">
 <span class="icon-[lucide--alert-triangle] text-lg flex-shrink-0" />
 <span class="text-sm">您需要修改密码后才能继续使用系统</span>
 </div>
 <!-- 新密码 -->
 <FormField v-slot="{ componentField }" name="new_password">
 <FormItem>
 <FormLabel class="text-foreground/80">新密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请输入新密码（至少 6 位）"
 autocomplete="new-password"
 class="pl-10 bg-muted/30 border-border/50 focus:border-amber-500/50 focus:ring-amber-500/20"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 确认密码 -->
 <FormField v-slot="{ componentField }" name="confirm_password">
 <FormItem>
 <FormLabel class="text-foreground/80">确认密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock-keyhole] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请再次输入新密码"
 autocomplete="new-password"
 class="pl-10 bg-muted/30 border-border/50 focus:border-amber-500/50 focus:ring-amber-500/20"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 提交按钮 -->
 <Button
 type="submit"
 class="w-full text-base font-medium bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 group relative overflow-hidden":disabled="isSubmitting"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <template v-if="isSubmitting">
 <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 提交中...
 </template>
 <template v-else>
 <span class="icon-[lucide--check] mr-2" />
 确认修改
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
