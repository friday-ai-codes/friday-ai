<script setup lang="ts">
/**
 * 个人资料页面
 * 用户查看/编辑自己的资料
 */
import type { MeUser } from '~/types'
import { onMounted, ref } from 'vue'
import { getMe } from '~/api/users'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { useAuthStore } from '~/stores/auth'
const authStore = useAuthStore
const { handleError } = useErrorHandler
const { success } = useToast
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
 catch (e: unknown) {
 handleError(e, '加载资料')
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
 success('资料已更新')
 }
 catch (e: unknown) {
 handleError(e, '保存资料')
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
 member: 'bg-primary/10 text-primary',
 viewer: 'bg-muted text-muted-foreground',
}
onMounted( => {
 loadProfile
})
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute inset-x-0 top-0 bg-linear-to-b from-primary/6 to-transparent" />
 </div>
 <div class="max-w-xl mx-auto space-y-8 relative">
 <!-- 页面标题 -->
 <section class="text-center pt-8 pb-4">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--user] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight mb-3">
 个人资料
 </h1>
 </section>
 <LoadingState v-if="loading" variant="spinner" text="加载资料..." />
 <template v-else-if="meData">
 <!-- 头像与基本信息 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
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
 class="w-24 rounded-full bg-primary/10 ring-4 ring-primary/20 ring-offset-2 ring-offset-background flex items-center justify-center text-3xl font-bold text-primary"
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
 <!-- 空间成员关系 -->
 <div class="group relative">
 <div class="card overflow-hidden">
 <div class="flex items-center gap-3 border-b border-border/50">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-2xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">
 我的空间
 </h2>
 <p class="text-sm text-muted-foreground">
 您所属的 {{ meData.project_memberships.length }} 个空间
 </p>
 </div>
 </div>
 <div class="">
 <div v-if="meData.project_memberships.length === 0" class="text-center py-6 text-muted-foreground">
 暂未加入任何空间
 </div>
 <div v-else class="space-y-3">
 <div
 v-for="membership in meData.project_memberships":key="membership.project_id"
 class="flex items-center justify-between rounded-xl bg-background/50 border border-border/30 hover:border-primary/20 transition-colors"
 >
 <div class="flex items-center gap-3">
 <div class="w-8 rounded-lg bg-primary/10 flex items-center justify-center">
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
