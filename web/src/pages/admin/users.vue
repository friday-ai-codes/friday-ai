<script setup lang="ts">
import UserManagementSettings from '~/components/settings/UserManagementSettings.vue'
definePage({
 meta: { requiresAdmin: true },
})
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
 </div>
 <div class="max-w-2xl mx-auto space-y-8 relative">
 <!-- 页面标题 -->
 <section class="text-center pt-8 pb-4">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--users] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent mb-3">
 用户管理
 </h1>
 <p class="text-muted-foreground max-w-md mx-auto">
 管理系统用户、邀请新成员、设置用户权限
 </p>
 </section>
 <UserManagementSettings />
 </div>
 </div>
</template>
