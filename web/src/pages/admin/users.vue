<script setup lang="ts">
import type { ColumnDef } from '@tanstack/vue-table'
import type { Invitation, SystemUser } from '~/types'
import { h } from 'vue'
import { createInvitation, listUsers, updateUser } from '~/api/users'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
definePage({
 meta: { requiresAdmin: true },
})
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
 handleError(e, '加载用户')
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
 handleError(e, '复制链接')
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
// --- DataTable 列定义 ---
const columns: ColumnDef<SystemUser> = [
 {
 accessorKey: 'username',
 header: '用户',
 cell: ({ row }) => {
 const user = row.original
 const displayName = user.display_name || user.username
 const initial = displayName.charAt(0).toUpperCase
 return h('div', { class: 'flex items-center gap-3' }, [
 h('div', {
 class: 'w-9 rounded-full bg-gradient-to-br from-primary/20 to-secondary/20 flex items-center justify-center text-sm font-medium shrink-0',
 }, initial),
 h('div', { class: 'min-w-0' }, [
 h('span', { class: 'font-medium text-sm text-foreground block' }, displayName),
 h('span', { class: 'text-xs text-muted-foreground' }, `@${user.username}`),
 ]),
 ])
 },
 enableSorting: true,
 },
 {
 id: 'role',
 header: '角色',
 cell: ({ row }) => row.original.is_superuser
 ? h(Badge, { variant: 'outline', class: 'text-xs' }, => '超级管理员'): h('span', { class: 'text-sm text-muted-foreground' }, '普通用户'),
 enableSorting: false,
 },
 {
 id: 'status',
 header: '状态',
 cell: ({ row }) => h(Badge, {
 variant: row.original.is_active ? 'default': 'destructive',
 class: 'text-xs',
 }, => row.original.is_active ? '启用': '禁用'),
 enableSorting: false,
 },
 {
 accessorKey: 'created_at',
 header: '注册时间',
 cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, formatDate(row.original.created_at)),
 enableSorting: true,
 },
 {
 id: 'actions',
 header: '操作',
 cell: ({ row }) => {
 if (row.original.is_superuser)
 return null
 return h(Button, {
 variant: 'secondary',
 size: 'sm',
 disabled: saving.value,
 onClick: (e: Event) => {
 e.stopPropagation
 toggleUserActive(row.original)
 },
 }, => row.original.is_active ? '禁用': '启用')
 },
 enableSorting: false,
 enableHiding: false,
 },
]
</script>
<template>
 <PageContainer show-background>
 <!-- 页头 -->
 <PageHeader
 icon="lucide--users"
 icon-gradient="from-primary/20 to-secondary/10"
 icon-color="text-primary"
 title="用户管理"
 description="管理系统用户、邀请新成员、设置用户权限"
 />
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
 <!-- 用户列表 DataTable -->
 <DataTable:data="users":columns="columns"
 table-id="admin-users-list":loading="loading"
 />
 </PageContainer>
</template>
