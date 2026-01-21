<script setup lang="ts">
/**
 * 账号设置页面
 * 管理员可以修改用户名、显示名和密码
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
import {
 Card,
 CardContent,
 CardDescription,
 CardHeader,
 CardTitle,
} from '~/components/ui/card'
import LoadingState from '~/components/common/LoadingState.vue'
const router = useRouter
const authStore = useAuthStore
// 加载状态
const loading = ref(true)
const saving = ref(false)
// 资料表单
const profileForm = ref({
 username: '',
 display_name: '',
})
// 密码表单 schema
const passwordSchema = toTypedSchema(z.object({
 old_password: z.string.min(1, '请输入当前密码'),
 new_password: z.string.min(6, '新密码至少 6 位'),
 confirm_password: z.string.min(6, '请确认新密码'),
}).refine(data => data.new_password === data.confirm_password, {
 message: '两次输入的密码不一致',
 path: ['confirm_password'],
}))
const { handleSubmit: handlePasswordSubmit, isSubmitting: isPasswordSubmitting, resetForm: resetPasswordForm } = useForm({
 validationSchema: passwordSchema,
})
// 加载管理员资料
async function loadProfile {
 loading.value = true
 try {
 const profile = await authStore.getAdminProfile
 profileForm.value = {
 username: profile.username,
 display_name: profile.display_name || '',
 }
 }
 catch (error) {
 console.error('Failed to load profile:', error)
 toast.error('加载资料失败')
 }
 finally {
 loading.value = false
 }
}
// 保存资料
async function saveProfile {
 saving.value = true
 try {
 await authStore.updateAdminProfile({
 username: profileForm.value.username,
 display_name: profileForm.value.display_name,
 })
 toast.success('资料已保存')
 }
 catch (error) {
 console.error('Failed to save profile:', error)
 toast.error(error instanceof Error ? error.message: '保存失败')
 }
 finally {
 saving.value = false
 }
}
// 修改密码
const onPasswordSubmit = handlePasswordSubmit(async (values) => {
 try {
 await authStore.adminChangePassword({
 old_password: values.old_password,
 new_password: values.new_password,
 })
 toast.success('密码已修改')
 resetPasswordForm
 }
 catch (error) {
 console.error('Failed to change password:', error)
 toast.error(error instanceof Error ? error.message: '修改密码失败')
 }
})
onMounted( => {
 loadProfile
})
</script>
<template>
 <div class="max-w-3xl mx-auto space-y-8">
 <!-- 返回按钮 -->
 <RouterLink to="/settings" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回系统设置
 </RouterLink>
 <!-- 页面标题 -->
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--user-cog] text-2xl text-indigo-500" />
 </div>
 <div>
 <h1 class="text-2xl font-bold">账号设置</h1>
 <p class="text-muted-foreground">
 管理您的账号信息和安全设置
 </p>
 </div>
 </div>
 </div>
 <LoadingState v-if="loading" variant="spinner" text="加载中..." />
 <template v-else>
 <!-- 基本信息 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-indigo-500/10 via-purple-500/10 to-indigo-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-indigo-500/5 to-purple-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--user] text-indigo-500" />
 基本信息
 </CardTitle>
 <CardDescription>
 修改您的用户名和显示名称
 </CardDescription>
 </CardHeader>
 <CardContent class="space-y-6 pt-6">
 <div class="space-y-3">
 <label class="text-sm font-medium">用户名</label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--at-sign] text-muted-foreground" />
 <Input
 v-model="profileForm.username"
 placeholder="请输入用户名"
 class="pl-10 bg-muted/30 border-border/50 focus:border-indigo-500/50"
 />
 </div>
 <p class="text-xs text-muted-foreground">
 用于登录系统的唯一标识
 </p>
 </div>
 <div class="space-y-3">
 <label class="text-sm font-medium">显示名称</label>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--smile] text-muted-foreground" />
 <Input
 v-model="profileForm.display_name"
 placeholder="请输入显示名称（可选）"
 class="pl-10 bg-muted/30 border-border/50 focus:border-indigo-500/50"
 />
 </div>
 <p class="text-xs text-muted-foreground">
 显示在界面上的名称
 </p>
 </div>
 <div class="flex justify-end pt-4 border-t border-border/50">
 <Button:disabled="saving"
 class="group relative overflow-hidden"
 @click="saveProfile"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="saving" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存信息
 </Button>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 修改密码 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-amber-500/10 via-orange-500/10 to-amber-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--lock] text-amber-500" />
 修改密码
 </CardTitle>
 <CardDescription>
 定期更换密码以保护账号安全
 </CardDescription>
 </CardHeader>
 <CardContent class="pt-6">
 <form class="space-y-6" @submit="onPasswordSubmit">
 <FormField v-slot="{ componentField }" name="old_password">
 <FormItem class="space-y-3">
 <FormLabel>当前密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请输入当前密码"
 autocomplete="current-password"
 class="pl-10 bg-muted/30 border-border/50 focus:border-amber-500/50"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <FormField v-slot="{ componentField }" name="new_password">
 <FormItem class="space-y-3">
 <FormLabel>新密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请输入新密码（至少 6 位）"
 autocomplete="new-password"
 class="pl-10 bg-muted/30 border-border/50 focus:border-amber-500/50"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <FormField v-slot="{ componentField }" name="confirm_password">
 <FormItem class="space-y-3">
 <FormLabel>确认新密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock-keyhole] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请再次输入新密码"
 autocomplete="new-password"
 class="pl-10 bg-muted/30 border-border/50 focus:border-amber-500/50"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <div class="flex justify-end pt-4 border-t border-border/50">
 <Button
 type="submit":disabled="isPasswordSubmitting"
 class="group relative overflow-hidden"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="isPasswordSubmitting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--shield-check] mr-2" />
 修改密码
 </Button>
 </div>
 </form>
 </CardContent>
 </Card>
 </div>
 <!-- 安全提示 -->
 <div class=" rounded-2xl border border-dashed border-border/50 bg-muted/20">
 <div class="flex items-start gap-3">
 <span class="icon-[lucide--shield] text-xl text-muted-foreground flex-shrink-0 mt-0.5" />
 <div class="space-y-2">
 <h3 class="font-medium">安全提示</h3>
 <ul class="list-disc list-inside space-y-1 text-sm text-muted-foreground">
 <li>请使用强密码，包含大小写字母、数字和特殊字符</li>
 <li>定期更换密码以保护账号安全</li>
 <li>请勿与他人共享您的账号信息</li>
 </ul>
 </div>
 </div>
 </div>
 </template>
 </div>
</template>
