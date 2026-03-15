<script setup lang="ts">
/**
 * 邀请接受页面
 * 公开访问，通过邀请令牌注册新用户
 */
import type { Invitation } from '~/types'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { acceptInvitation, validateInvitation } from '~/api/users'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
const route = useRoute
const router = useRouter
const token = (route.params as { token: string }).token
// 页面状态
type PageState = 'loading' | 'valid' | 'invalid' | 'success'
const pageState = ref<PageState>('loading')
const invitation = ref<Invitation | null>(null)
const errorMessage = ref('')
// 注册表单
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const displayName = ref('')
const submitting = ref(false)
async function loadInvitation {
 pageState.value = 'loading'
 try {
 invitation.value = await validateInvitation(token)
 // 预填邮箱显示名
 if (invitation.value.email) {
 displayName.value = invitation.value.email.split('@')[0]
 }
 pageState.value = 'valid'
 }
 catch (error: any) {
 if (error?.status === 410) {
 errorMessage.value = '此邀请链接已过期或已被使用'
 }
 else if (error?.status === 404) {
 errorMessage.value = '邀请链接不存在'
 }
 else {
 errorMessage.value = '邀请链接无效'
 }
 pageState.value = 'invalid'
 }
}
async function handleRegister {
 if (!username.value.trim) {
 toast.error('请输入用户名')
 return
 }
 if (username.value.length < 3) {
 toast.error('用户名至少 3 个字符')
 return
 }
 if (!password.value || password.value.length < 6) {
 toast.error('密码至少 6 个字符')
 return
 }
 if (password.value !== confirmPassword.value) {
 toast.error('两次密码输入不一致')
 return
 }
 submitting.value = true
 try {
 await acceptInvitation({
 token,
 username: username.value.trim,
 password: password.value,
 display_name: displayName.value.trim,
 })
 pageState.value = 'success'
 toast.success('注册成功！即将跳转到登录页')
 setTimeout( => {
 router.push('/login')
 }, 2000)
 }
 catch (error: any) {
 if (error?.status === 409) {
 toast.error('该用户名已被使用，请换一个')
 }
 else if (error?.status === 410) {
 toast.error('邀请链接已失效')
 pageState.value = 'invalid'
 errorMessage.value = '此邀请链接已过期或已被使用'
 }
 else {
 toast.error('注册失败，请重试')
 }
 }
 finally {
 submitting.value = false
 }
}
function formatExpiry(dateStr: string) {
 return new Date(dateStr).toLocaleDateString('zh-CN', {
 year: 'numeric',
 month: 'long',
 day: 'numeric',
 hour: '2-digit',
 minute: '2-digit',
 })
}
onMounted( => {
 loadInvitation
})
</script>
<template>
 <div class="min-h-screen flex items-center justify-center relative overflow-hidden bg-background">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute bottom-0 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <div class="w-full max-w-md px-4">
 <!-- Logo / 品牌区域 -->
 <div class="text-center mb-8">
 <div class="inline-flex items-center justify-center mb-4 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--user-plus] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent">
 加入 Friday AI
 </h1>
 </div>
 <!-- 加载中 -->
 <div v-if="pageState === 'loading'" class="text-center py-12">
 <span class="icon-[lucide--loader-2] animate-spin text-4xl text-muted-foreground" />
 <p class="mt-4 text-muted-foreground">
 正在验证邀请链接...
 </p>
 </div>
 <!-- 无效的邀请链接 -->
 <div
 v-else-if="pageState === 'invalid'"
 class="rounded-2xl bg-card/80 backdrop-blur-sm border border-destructive/30 text-center space-y-4"
 >
 <div class="inline-flex items-center justify-center w-16 rounded-full bg-destructive/10">
 <span class="icon-[lucide--x-circle] text-3xl text-destructive" />
 </div>
 <h2 class="text-xl font-semibold">
 邀请链接无效
 </h2>
 <p class="text-muted-foreground">
 {{ errorMessage }}
 </p>
 <Button variant="outline" @click="router.push('/login')">
 返回登录
 </Button>
 </div>
 <!-- 注册成功 -->
 <div
 v-else-if="pageState === 'success'"
 class="rounded-2xl bg-card/80 backdrop-blur-sm border border-green-500/30 text-center space-y-4"
 >
 <div class="inline-flex items-center justify-center w-16 rounded-full bg-green-500/10">
 <span class="icon-[lucide--check-circle] text-3xl text-green-500" />
 </div>
 <h2 class="text-xl font-semibold">
 注册成功！
 </h2>
 <p class="text-muted-foreground">
 账号已创建，正在跳转到登录页...
 </p>
 <span class="icon-[lucide--loader-2] animate-spin text-2xl text-muted-foreground" />
 </div>
 <!-- 注册表单 -->
 <div
 v-else
 class="card overflow-hidden"
 >
 <!-- 邀请信息 -->
 <div class=" border-b border-border/50 bg-gradient-to-r from-primary/5 to-secondary/5">
 <p class="text-sm text-muted-foreground">
 您收到了来自团队的邀请。链接有效期至
 <span class="font-medium text-foreground">{{ invitation ? formatExpiry(invitation.expires_at): '' }}</span>
 </p>
 <p v-if="invitation?.email" class="text-xs text-muted-foreground mt-1">
 账号将关联邮箱：<span class="font-mono text-foreground/70">{{ invitation.email }}</span>
 </p>
 </div>
 <!-- 表单 -->
 <div class=" space-y-4">
 <div class="space-y-1.5">
 <Label for="username">
 用户名 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="username"
 v-model="username"
 placeholder="至少 3 个字符"
 autocomplete="username"
 class="bg-background/50"
 />
 </div>
 <div class="space-y-1.5">
 <Label for="display-name">
 显示名称（可选）
 </Label>
 <Input
 id="display-name"
 v-model="displayName"
 placeholder="您的姓名或昵称"
 class="bg-background/50"
 />
 </div>
 <div class="space-y-1.5">
 <Label for="password">
 密码 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="password"
 v-model="password"
 type="password"
 placeholder="至少 6 个字符"
 autocomplete="new-password"
 class="bg-background/50"
 />
 </div>
 <div class="space-y-1.5">
 <Label for="confirm-password">
 确认密码 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="confirm-password"
 v-model="confirmPassword"
 type="password"
 placeholder="再次输入密码"
 autocomplete="new-password"
 class="bg-background/50"
 />
 </div>
 <Button
 class="w-full gap-2 mt-2":disabled="submitting"
 @click="handleRegister"
 >
 <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin text-sm" />
 <span v-else class="icon-[lucide--user-check] text-sm" />
 {{ submitting ? '注册中...': '创建账号' }}
 </Button>
 </div>
 </div>
 <!-- 返回登录 -->
 <div class="text-center mt-6">
 <button
 class="text-sm text-muted-foreground hover:text-foreground transition-colors"
 @click="router.push('/login')"
 >
 已有账号？返回登录
 </button>
 </div>
 </div>
 </div>
</template>
<route lang="yaml">
meta:
 layout: false
</route>
