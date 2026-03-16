<script setup lang="ts">
/**
 * 个人资料页面
 * 用户查看/编辑自己的资料
 */
import type { MeUser } from '~/types'
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { getMe } from '~/api/users'
import { useAuthStore } from '~/stores/auth'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import LoadingState from '~/components/common/LoadingState.vue'
const authStore = useAuthStore
const meData = ref<MeUser | null>(null)
const loading = ref(true)
const saving = ref(false)
const displayName = ref('')
const editingName = ref(false)
async function loadProfile {
 loading.value = true
 try {
 meData.value = await getMe
 displayName.value = meData.value.display_name
 }
 catch {
 toast.error('加载资料失败')
 }
 finally {
 loading.value = false
 }
}
async function saveDisplayName {
 saving.value = true
 try {
 await authStore.updateDisplayName(displayName.value)
 if (meData.value) {
 meData.value.display_name = displayName.value
 }
 editingName.value = false
 toast.success('资料已更新')
 }
 catch {
 toast.error('保存失败')
 }
 finally {
 saving.value = false
 }
}
const roleLabels: Record<string, string> = {
 admin: '管理员',
 member: '成员',
 viewer: '观察者',
}
const roleColors: Record<string, string> = {
 admin: 'bg-primary/10 text-primary',
 member: 'bg-blue-500/10 text-blue-600',
 viewer: 'bg-muted text-muted-foreground',
}
onMounted( => {
 loadProfile
})
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <div class="max-w-xl mx-auto space-y-8 relative">
 <!-- 页面标题 -->
 <section class="text-center pt-8 pb-4">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--user] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent mb-3">
 个人资料
 </h1>
 </section>
 <LoadingState v-if="loading" variant="spinner" text="加载资料..." />
 <template v-else-if="meData">
 <!-- 头像与基本信息 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-primary/5 to-secondary/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--user-circle] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 个人信息
 </h2>
 <p class="text-sm text-muted-foreground">
 查看和编辑您的基本信息
 </p>
 </div>
 </div>
 <div class=" flex flex-col items-center gap-6">
 <!-- 头像 -->
 <div class="relative">
 <img
 v-if="meData.gravatar_url":src="meData.gravatar_url":alt="meData.display_name || meData.username"
 class="w-24 rounded-full ring-4 ring-primary/20 ring-offset-2 ring-offset-background"
 >
 <div
 v-else
 class="w-24 rounded-full bg-gradient-to-br from-primary/30 to-secondary/30 ring-4 ring-primary/20 ring-offset-2 ring-offset-background flex items-center justify-center text-3xl font-bold text-primary"
 >
 {{ (meData.display_name || meData.username).charAt(0).toUpperCase }}
 </div>
 <div class="absolute -bottom-1 -right-1 w-6 rounded-full bg-green-500 ring-2 ring-background" />
 </div>
 <!-- 名称编辑 -->
 <div class="text-center w-full">
 <template v-if="editingName">
 <div class="flex items-center gap-2 justify-center max-w-xs mx-auto">
 <Input
 v-model="displayName"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 placeholder="输入显示名称"
 @keyup.enter="saveDisplayName"
 />
 <Button
 size="sm":disabled="saving"
 @click="saveDisplayName"
 >
 <span v-if="saving" class="icon-[lucide--loader-2] animate-spin" />
 <span v-else class="icon-[lucide--check]" />
 </Button>
 <Button
 size="sm"
 variant="outline"
 @click="editingName = false; displayName = meData!.display_name"
 >
 <span class="icon-[lucide--x]" />
 </Button>
 </div>
 </template>
 <template v-else>
 <div class="flex items-center gap-2 justify-center">
 <h2 class="text-2xl font-bold">
 {{ meData.display_name || meData.username }}
 </h2>
 <button
 class="text-muted-foreground hover:text-primary transition-colors"
 @click="editingName = true"
 >
 <span class="icon-[lucide--pencil] text-sm" />
 </button>
 </div>
 </template>
 <p class="text-muted-foreground mt-1">
 @{{ meData.username }}
 </p>
 <p v-if="meData.email" class="text-sm text-muted-foreground mt-0.5">
 {{ meData.email }}
 </p>
 <div class="flex items-center justify-center gap-2 mt-3">
 <span v-if="meData.is_superuser" class="text-xs px-2 py-1 rounded-full bg-primary/10 text-primary font-medium">
 超级管理员
 </span>
 <span class="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
 注册于 {{ new Date(meData.created_at).toLocaleDateString('zh-CN') }}
 </span>
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 项目成员关系 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50 bg-gradient-to-r from-secondary/5 to-primary/5">
 <div class=".5 rounded-xl bg-gradient-to-br from-secondary/20 to-secondary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 我的项目
 </h2>
 <p class="text-sm text-muted-foreground">
 您所属的 {{ meData.project_memberships.length }} 个项目
 </p>
 </div>
 </div>
 <div class="">
 <div v-if="meData.project_memberships.length === 0" class="text-center py-6 text-muted-foreground">
 暂未加入任何项目
 </div>
 <div v-else class="space-y-3">
 <div
 v-for="membership in meData.project_memberships":key="membership.project_id"
 class="flex items-center justify-between rounded-xl bg-background/50 border border-border/30 hover:border-primary/20 transition-colors"
 >
 <div class="flex items-center gap-3">
 <div class="w-8 rounded-lg bg-gradient-to-br from-primary/20 to-secondary/20 flex items-center justify-center">
 <span class="icon-[lucide--folder] text-sm text-primary" />
 </div>
 <span class="font-medium text-sm">{{ membership.project_name }}</span>
 </div>
 <span
 class="text-xs px-2 py-1 rounded-full font-medium":class="roleColors[membership.role] ?? 'bg-muted text-muted-foreground'"
 >
 {{ roleLabels[membership.role] ?? membership.role }}
 </span>
 </div>
 </div>
 </div>
 </div>
 </div>
 </template>
 </div>
 </div>
</template>
