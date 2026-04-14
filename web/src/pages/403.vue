<script setup lang="ts">
/**
 * 403 无权访问页面
 */
import { Button } from '~/components/ui/button'
const router = useRouter
function goHome {
 router.push('/')
}
function goBack {
 router.back
}
</script>
<template>
 <div class="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
 <!-- 背景装饰 -->
 <div class="absolute inset-0 -z-10">
 <div class="absolute -top-40 -right-40 w-96 bg-primary/10 rounded-full blur-3xl" />
 <div class="absolute -bottom-40 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-destructive/10 rounded-full blur-3xl" />
 <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full blur-3xl" />
 </div>
 <!-- 内容卡片 -->
 <div class="w-full max-w-md mx-4">
 <div class="relative">
 <!-- 卡片光晕 -->
 <!-- 卡片主体 -->
 <div class="relative bg-card/80 backdrop-blur-xl rounded-2xl border border-border/50 shadow-2xl shadow-destructive/5 text-center">
 <!-- 图标 -->
 <div class="inline-flex items-center justify-center mb-6 rounded-2xl bg-gradient-to-br from-destructive/10 via-secondary/20 to-destructive/10 border border-destructive/10">
 <span class="icon-[lucide--shield-off] text-5xl text-destructive" />
 </div>
 <!-- 标题 -->
 <h1 class="text-2xl font-bold text-foreground mb-2">
 无权访问
 </h1>
 <!-- 副标题 -->
 <p class="text-muted-foreground mb-8">
 您没有权限访问此页面
 </p>
 <!-- 操作按钮 -->
 <div class="flex flex-col gap-3">
 <Button
 class="w-full text-base font-medium"
 @click="goHome"
 >
 <span class="icon-[lucide--home] mr-2" />
 返回首页
 </Button>
 <Button
 variant="outline"
 class="w-full text-base font-medium bg-muted/20 border-border/50 hover:border-primary/30 hover:bg-primary/5"
 @click="goBack"
 >
 <span class="icon-[lucide--arrow-left] mr-2" />
 返回上一页
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
<route lang="yaml">
meta:
 layout: false
</route>
