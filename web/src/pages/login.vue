<script setup lang="ts">
/**
 * 登录页面
 */
import { useForm } from 'vee-validate'
import { toTypedSchema } from '@vee-validate/zod'
import * as z from 'zod'
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
import {
 Card,
 CardContent,
 CardDescription,
 CardHeader,
 CardTitle,
} from '~/components/ui/card'
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
 await authStore.login(values.username, values.password)
 // 登录成功，跳转到原页面或首页
 const redirect = route.query.redirect as string || '/'
 router.push(redirect)
 } catch (e) {
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
 <div class="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
 <Card class="w-full max-w-md">
 <CardHeader class="text-center">
 <CardTitle class="text-2xl font-bold">
 Friday
 </CardTitle>
 <CardDescription>
 AI 驱动的开发自动化平台
 </CardDescription>
 </CardHeader>
 <CardContent>
 <form class="space-y-6" @submit="onSubmit">
 <!-- 错误提示 -->
 <div
 v-if="loginError"
 class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm"
 >
 {{ loginError }}
 </div>
 <!-- 用户名 -->
 <FormField v-slot="{ componentField }" name="username">
 <FormItem>
 <FormLabel>用户名</FormLabel>
 <FormControl>
 <Input
 type="text"
 placeholder="请输入用户名"
 autocomplete="username"
 v-bind="componentField"
 />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 密码 -->
 <FormField v-slot="{ componentField }" name="password">
 <FormItem>
 <FormLabel>密码</FormLabel>
 <FormControl>
 <Input
 type="password"
 placeholder="请输入密码"
 autocomplete="current-password"
 v-bind="componentField"
 />
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <!-- 登录按钮 -->
 <Button
 type="submit"
 class="w-full":disabled="isSubmitting"
 >
 <template v-if="isSubmitting">
 <span class="mr-2">
 <svg class="animate-spin w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
 <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
 <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 work-item.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
 </svg>
 </span>
 登录中...
 </template>
 <template v-else>
 登录
 </template>
 </Button>
 </form>
 <!-- 默认账户提示（仅开发环境） -->
 <div class="mt-6 text-center text-sm text-gray-500">
 <p>默认管理员账户：admin / admin123</p>
 </div>
 </CardContent>
 </Card>
 </div>
</template>
<route lang="yaml">
meta:
 layout: false
</route>
