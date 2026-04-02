<script setup lang="ts">
import type { Invitation, SystemUser } from '~/types'
import { onMounted, ref } from 'vue'
import { createInvitation, listUsers, updateUser } from '~/api/users'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
const { handleError } = useErrorHandler
const { success } = useToast
const users = ref<SystemUser>
const loading = ref(true)
const saving = ref(false)
// 邀请创建
const inviteEmail = ref('')
const creatingInvite = ref(false)
const newInvitation = ref<Invitation | null>(null)
const inviteLink = ref('')
async function loadUsers {
 loading.value = true
 try {
 users.value = await listUsers
 }
 catch (e: unknown) {
 handleError(e, '加载用户列表')
 }
 finally {
 loading.value = false
 }
}
async function toggleUserActive(user: SystemUser) {
 saving.value = true
 try {
 const updated = await updateUser(user.id, { is_active: !user.is_active })
 const idx = users.value.findIndex(u => u.id === user.id)
 if (idx !== -1)
 users.value[idx] = updated
 success(updated.is_active ? '用户已启用': '用户已禁用')
 }
 catch (e: unknown) {
 handleError(e, '切换用户状态')
 }
 finally {
 saving.value = false
 }
}
async function generateInviteLink {
 creatingInvite.value = true
 newInvitation.value = null
 inviteLink.value = ''
 try {
 const invitation = await createInvitation(inviteEmail.value.trim || undefined)
 newInvitation.value = invitation
 const baseUrl = window.location.origin
 inviteLink.value = `${baseUrl}/invite/${invitation.token}`
 inviteEmail.value = ''
 success('邀请链接已生成')
 }
 catch (e: unknown) {
 handleError(e, '生成邀请链接')
 }
 finally {
 creatingInvite.value = false
 }
}
async function copyInviteLink {
 if (!inviteLink.value)
 return
 try {
 await navigator.clipboard.writeText(inviteLink.value)
 success('链接已复制到剪贴板')
 }
 catch (e: unknown) {
 handleError(e, '复制')
 }
}
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleDateString('zh-CN', {
 year: 'numeric',
 month: 'short',
 day: 'numeric',
 })
}
onMounted( => {
 loadUsers
})
</script>
<template>
 <div class="space-y-8">
 <!-- 邀请新用户 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-primary/5 to-secondary/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--user-plus] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 邀请新用户
 </h2>
 <p class="text-sm text-muted-foreground">
 生成邀请链接，有效期 7 天
 </p>
 </div>
 </div>
 <div class=" space-y-4">
 <div class="flex gap-3">
 <div class="flex-1">
 <Label for="invite-email" class="text-xs text-muted-foreground mb-1.5 block">
 预填邮箱（可选）
 </Label>
 <Input
 id="invite-email"
 v-model="inviteEmail"
 type="email"
 placeholder="user@example.com"
 class="bg-background/50"
 />
 </div>
 <div class="flex items-end">
 <button:disabled="creatingInvite"
 class="btn btn-primary"
 @click="generateInviteLink"
 >
 <span v-if="creatingInvite" class="icon-[lucide--loader-2] animate-spin" />
 <span v-else class="icon-[lucide--link]" />
 生成链接
 </button>
 </div>
 </div>
 <!-- 生成的邀请链接 -->
 <div
 v-if="inviteLink"
 class=" rounded-xl bg-primary/5 border border-primary/20 space-y-2"
 >
 <div class="flex items-center justify-between gap-2">
 <p class="text-xs text-muted-foreground">
 邀请链接（有效期至 {{ newInvitation ? formatDate(newInvitation.expires_at): '' }}）
 </p>
 <button
 class="btn btn-ghost btn-sm"
 @click="copyInviteLink"
 >
 <span class="icon-[lucide--copy]" />
 复制
 </button>
 </div>
 <p class="text-sm font-mono break-all text-foreground/70 bg-background/50 rounded-lg ">
 {{ inviteLink }}
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- 用户列表 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-secondary/5 to-primary/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-secondary/20 to-secondary/10 flex items-center justify-center">
 <span class="icon-[lucide--users] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 用户管理
 </h2>
 <p class="text-sm text-muted-foreground">
 查看系统所有用户，启用或禁用账号
 </p>
 </div>
 </div>
 <div class="">
 <div v-if="loading" class="flex items-center justify-center py-8">
 <span class="icon-[lucide--loader-2] animate-spin text-2xl text-muted-foreground" />
 </div>
 <div v-else-if="users.length === 0" class="text-center py-8 text-muted-foreground">
 暂无用户
 </div>
 <div v-else class="space-y-3">
 <div
 v-for="user in users":key="user.id"
 class="flex items-center justify-between rounded-xl bg-background/50 border border-border/30 hover:border-primary/20 transition-colors"
 >
 <div class="flex items-center gap-3">
 <div class="w-9 rounded-full bg-gradient-to-br from-primary/20 to-secondary/20 flex items-center justify-center text-sm font-medium">
 {{ (user.display_name || user.username).charAt(0).toUpperCase }}
 </div>
 <div>
 <div class="flex items-center gap-2">
 <span class="font-medium text-sm">{{ user.display_name || user.username }}</span>
 <span v-if="user.is_superuser" class="text-xs px-1.5 py-0.5 rounded-md bg-primary/10 text-primary font-medium">
 超级管理员
 </span>
 <span:class="user.is_active ? 'bg-green-500/10 text-green-600': 'bg-destructive/10 text-destructive'"
 class="text-xs px-1.5 py-0.5 rounded-md font-medium"
 >
 {{ user.is_active ? '启用': '禁用' }}
 </span>
 </div>
 <p class="text-xs text-muted-foreground">
 @{{ user.username }} · 注册于 {{ formatDate(user.created_at) }}
 </p>
 </div>
 </div>
 <button
 v-if="!user.is_superuser"
 class="btn btn-secondary btn-sm":disabled="saving"
 @click="toggleUserActive(user)"
 >
 {{ user.is_active ? '禁用': '启用' }}
 </button>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
