<script setup lang="ts">
import { toTypedSchema } from '@vee-validate/zod'
import { useForm } from 'vee-validate'
import { VueFinalModal } from 'vue-final-modal'
import * as z from 'zod'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { Button } from '~/components/ui/button'
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '~/components/ui/form'
import { Input } from '~/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { useAuthStore } from '~/stores/auth'
const emit = defineEmits<{
 confirm:
 cancel:
 closed:
}>
const authStore = useAuthStore
const { handleError } = useErrorHandler
const { success } = useToast
// ============================================================================
// State
// ============================================================================
const loading = ref(false)
const activeTab = ref('profile')
// ============================================================================
// Profile Form
// ============================================================================
const profileSchema = toTypedSchema(z.object({
 username: z.string.min(1, '请输入用户名'),
 display_name: z.string.optional,
}))
const { handleSubmit: handleProfileSubmit, isSubmitting: isProfileSubmitting, setValues: setProfileValues } = useForm({
 validationSchema: profileSchema,
})
const onProfileSubmit = handleProfileSubmit(async (values) => {
 try {
 await authStore.updateAdminProfile({
 username: values.username,
 display_name: values.display_name || '',
 })
 success('保存成功', '个人资料已更新')
 // Don't close modal, just show success
 }
 catch (e: unknown) {
 handleError(e, '保存资料')
 }
})
// ============================================================================
// Password Form
// ============================================================================
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
const onPasswordSubmit = handlePasswordSubmit(async (values) => {
 try {
 await authStore.adminChangePassword({
 old_password: values.old_password,
 new_password: values.new_password,
 })
 success('修改成功', '密码已修改')
 resetPasswordForm
 }
 catch (e: unknown) {
 handleError(e, '修改密码')
 }
})
// ============================================================================
// Lifecycle
// ============================================================================
async function loadProfile {
 loading.value = true
 try {
 const profile = await authStore.getAdminProfile
 setProfileValues({
 username: profile.username,
 display_name: profile.display_name || '',
 })
 }
 catch (e: unknown) {
 handleError(e, '加载用户信息')
 }
 finally {
 loading.value = false
 }
}
onMounted( => {
 loadProfile
})
function handleCancel {
 emit('cancel')
}
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 sticky top-0 bg-card z-10">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/10">
 <span class="icon-[lucide--user-cog] text-xl text-indigo-500" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 账号设置
 </h3>
 <p class="text-sm text-muted-foreground">
 管理您的个人资料和安全设置
 </p>
 </div>
 </div>
 <button
 type="button"
 class=" rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="handleCancel"
 >
 <span class="icon-[lucide--x] text-lg" />
 </button>
 </div>
 <!-- Body -->
 <div class="px-6 py-5">
 <Tabs v-model="activeTab" default-value="profile" class="w-full">
 <TabsList class="grid w-full grid-cols-2 mb-6">
 <TabsTrigger value="profile">
 基本信息
 </TabsTrigger>
 <TabsTrigger value="security">
 安全设置
 </TabsTrigger>
 </TabsList>
 <!-- Profile Tab -->
 <TabsContent value="profile" class="space-y-4">
 <form class="space-y-4" @submit="onProfileSubmit">
 <FormField v-slot="{ componentField }" name="username">
 <FormItem class="space-y-2">
 <FormLabel>用户名</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--at-sign] text-muted-foreground" />
 <Input
 placeholder="请输入用户名"
 class="pl-10"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <FormField v-slot="{ componentField }" name="display_name">
 <FormItem class="space-y-2">
 <FormLabel>显示名称</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--smile] text-muted-foreground" />
 <Input
 placeholder="请输入显示名称"
 class="pl-10"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <div class="flex justify-end pt-4">
 <Button type="submit":disabled="isProfileSubmitting || loading">
 <span v-if="isProfileSubmitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存信息
 </Button>
 </div>
 </form>
 </TabsContent>
 <!-- Security Tab -->
 <TabsContent value="security" class="space-y-4">
 <form class="space-y-4" @submit="onPasswordSubmit">
 <FormField v-slot="{ componentField }" name="old_password">
 <FormItem class="space-y-2">
 <FormLabel>当前密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请输入当前密码"
 autocomplete="current-password"
 class="pl-10"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <FormField v-slot="{ componentField }" name="new_password">
 <FormItem class="space-y-2">
 <FormLabel>新密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--key] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请输入新密码（至少 6 位）"
 autocomplete="new-password"
 class="pl-10"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <FormField v-slot="{ componentField }" name="confirm_password">
 <FormItem class="space-y-2">
 <FormLabel>确认新密码</FormLabel>
 <FormControl>
 <div class="relative">
 <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--lock-keyhole] text-muted-foreground" />
 <Input
 type="password"
 placeholder="请再次输入新密码"
 autocomplete="new-password"
 class="pl-10"
 v-bind="componentField"
 />
 </div>
 </FormControl>
 <FormMessage />
 </FormItem>
 </FormField>
 <div class="flex justify-end pt-4">
 <Button type="submit":disabled="isPasswordSubmitting">
 <span v-if="isPasswordSubmitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--shield-check] mr-2" />
 修改密码
 </Button>
 </div>
 </form>
 </TabsContent>
 </Tabs>
 </div>
 </VueFinalModal>
</template>
