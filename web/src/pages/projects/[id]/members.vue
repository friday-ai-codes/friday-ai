<script setup lang="ts">
/**
 * 项目成员管理页面
 */
import type { ProjectMembership, SystemUser } from '~/types'
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '~/api/client'
import { addProjectMember, listProjectMembers, removeProjectMember, updateProjectMember } from '~/api/members'
import { listUsers } from '~/api/users'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
const route = useRoute
const projectId = (route.params as { id: string }).id
const { confirm } = useConfirmDialog
const { handleError } = useErrorHandler
const { success } = useToast
const members = ref<ProjectMembership>
const loading = ref(true)
const saving = ref(false)
// 添加成员
const showAddForm = ref(false)
const allUsers = ref<SystemUser>
const selectedUserId = ref('')
const selectedRole = ref<'admin' | 'member' | 'viewer'>('member')
const loadingUsers = ref(false)
const roleLabels: Record<string, string> = {
 admin: '管理员',
 member: '成员',
 viewer: '观察者',
}
async function loadMembers {
 loading.value = true
 try {
 members.value = await listProjectMembers(projectId)
 }
 catch (e: unknown) {
 handleError(e, '加载成员列表')
 }
 finally {
 loading.value = false
 }
}
async function openAddForm {
 showAddForm.value = true
 loadingUsers.value = true
 try {
 allUsers.value = await listUsers
 }
 catch (e: unknown) {
 handleError(e, '加载用户列表')
 }
 finally {
 loadingUsers.value = false
 }
}
// 过滤出还不是成员的用户
function getNonMembers {
 const memberUserIds = new Set(members.value.map(m => m.user.id))
 return allUsers.value.filter(u => !memberUserIds.has(u.id) && u.is_active)
}
async function handleAddMember {
 if (!selectedUserId.value) {
 handleError(new Error('请选择用户'), '添加成员')
 return
 }
 saving.value = true
 try {
 const membership = await addProjectMember(projectId, {
 user_id: selectedUserId.value,
 role: selectedRole.value,
 })
 members.value.push(membership)
 showAddForm.value = false
 selectedUserId.value = ''
 selectedRole.value = 'member'
 success('成员已添加')
 }
 catch (e: unknown) {
 if (e instanceof ApiError && e.status === 409) {
 handleError(e, '添加成员')
 }
 else {
 handleError(e, '添加成员')
 }
 }
 finally {
 saving.value = false
 }
}
async function handleRoleChange(member: ProjectMembership, newRole: 'admin' | 'member' | 'viewer') {
 saving.value = true
 try {
 const updated = await updateProjectMember(projectId, member.user.id, { role: newRole })
 const idx = members.value.findIndex(m => m.id === member.id)
 if (idx !== -1)
 members.value[idx] = updated
 success('角色已更新')
 }
 catch (e: unknown) {
 handleError(e, '更新角色')
 }
 finally {
 saving.value = false
 }
}
async function handleRemoveMember(member: ProjectMembership) {
 const confirmed = await confirm({
 title: '移除成员',
 description: `确定要移除 ${member.user.display_name || member.user.username} 吗？`,
 confirmText: '移除',
 variant: 'destructive',
 })
 if (!confirmed)
 return
 saving.value = true
 try {
 await removeProjectMember(projectId, member.user.id)
 members.value = members.value.filter(m => m.id !== member.id)
 success('成员已移除')
 }
 catch (e: unknown) {
 handleError(e, '移除成员')
 }
 finally {
 saving.value = false
 }
}
onMounted( => {
 loadMembers
})
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-primary/10 rounded-full blur-3xl" />
 </div>
 <div class="max-w-2xl mx-auto space-y-8 relative pt-8">
 <!-- 页面标题 -->
 <section class="flex items-center justify-between">
 <div>
 <h1 class="text-2xl font-bold tracking-tight">
 项目成员管理
 </h1>
 <p class="text-sm text-muted-foreground mt-1">
 管理项目成员的访问权限和角色
 </p>
 </div>
 <Button
 class="gap-2"
 @click="openAddForm"
 >
 <span class="icon-[lucide--user-plus] text-sm" />
 添加成员
 </Button>
 </section>
 <!-- 添加成员表单 -->
 <div
 v-if="showAddForm"
 class="rounded-2xl bg-card/80 backdrop-blur-sm border border-primary/30 space-y-4"
 >
 <h2 class="font-semibold text-sm">
 添加新成员
 </h2>
 <div v-if="loadingUsers" class="flex items-center gap-2 text-muted-foreground text-sm">
 <span class="icon-[lucide--loader-2] animate-spin" />
 加载用户列表...
 </div>
 <template v-else>
 <div class="flex gap-3">
 <Select v-model="selectedUserId" class="flex-1">
 <SelectTrigger class="bg-background/50">
 <SelectValue placeholder="选择用户" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="u in getNonMembers":key="u.id":value="u.id"
 >
 {{ u.display_name || u.username }}（@{{ u.username }}）
 </SelectItem>
 <div v-if="getNonMembers.length === 0" class="py-2 px-3 text-sm text-muted-foreground">
 所有用户已是成员
 </div>
 </SelectContent>
 </Select>
 <Select v-model="selectedRole">
 <SelectTrigger class="w-32 bg-background/50">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="admin">
 管理员
 </SelectItem>
 <SelectItem value="member">
 成员
 </SelectItem>
 <SelectItem value="viewer">
 观察者
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div class="flex gap-2">
 <Button
 size="sm":disabled="saving || !selectedUserId"
 @click="handleAddMember"
 >
 确认添加
 </Button>
 <Button
 size="sm"
 variant="outline"
 @click="showAddForm = false"
 >
 取消
 </Button>
 </div>
 </template>
 </div>
 <!-- 成员列表 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--users] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 成员列表
 </h2>
 <p class="text-sm text-muted-foreground">
 共 {{ members.length }} 位成员
 </p>
 </div>
 </div>
 <div class="">
 <div v-if="loading" class="flex items-center justify-center py-8">
 <span class="icon-[lucide--loader-2] animate-spin text-2xl text-muted-foreground" />
 </div>
 <div v-else-if="members.length === 0" class="text-center py-8 text-muted-foreground">
 暂无成员，点击「添加成员」开始添加
 </div>
 <div v-else class="space-y-3">
 <div
 v-for="member in members":key="member.id"
 class="flex items-center justify-between rounded-xl bg-background/50 border border-border/30 hover:border-primary/20 transition-colors"
 >
 <div class="flex items-center gap-3">
 <div class="w-9 rounded-full bg-primary/10 flex items-center justify-center text-sm font-medium">
 {{ (member.user.display_name || member.user.username).charAt(0).toUpperCase }}
 </div>
 <div>
 <p class="font-medium text-sm">
 {{ member.user.display_name || member.user.username }}
 </p>
 <p class="text-xs text-muted-foreground">
 @{{ member.user.username }}
 </p>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <Select:model-value="member.role":disabled="saving"
 @update:model-value="(v) => handleRoleChange(member, v as 'admin' | 'member' | 'viewer')"
 >
 <SelectTrigger class="w-28 text-xs bg-background/50">
 <SelectValue>{{ roleLabels[member.role] }}</SelectValue>
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="admin">
 管理员
 </SelectItem>
 <SelectItem value="member">
 成员
 </SelectItem>
 <SelectItem value="viewer">
 观察者
 </SelectItem>
 </SelectContent>
 </Select>
 <Button
 variant="ghost"
 size="sm":disabled="saving"
 class=" w-8 text-muted-foreground hover:text-destructive"
 @click="handleRemoveMember(member)"
 >
 <span class="icon-[lucide--user-minus] text-sm" />
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
