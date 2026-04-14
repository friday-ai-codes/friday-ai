<script setup lang="ts">
import OIDCProviderSettings from '~/components/settings/OIDCProviderSettings.vue'
definePage({
 meta: { requiresAdmin: true },
})
</script>
<template>
 <div class="min-h-[calc(100vh-8rem)] relative">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute inset-x-0 top-0 bg-linear-to-b from-primary/6 to-transparent" />
 </div>
 <div class="max-w-2xl mx-auto space-y-8 relative">
 <!-- 页面标题 -->
 <section class="text-center pt-8 pb-4">
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-primary/10 via-secondary/50 to-primary/10 backdrop-blur-sm border border-primary/10">
 <span class="icon-[lucide--shield-check] text-4xl text-primary" />
 </div>
 <h1 class="text-3xl font-bold tracking-tight mb-3">
 OIDC 认证
 </h1>
 <p class="text-muted-foreground max-w-md mx-auto">
 配置 OpenID Connect 身份提供商，启用单点登录
 </p>
 </section>
 <OIDCProviderSettings />
 </div>
 </div>
</template>
