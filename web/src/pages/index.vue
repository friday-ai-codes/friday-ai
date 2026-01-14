<script setup lang="ts">
import { useHead } from '@vueuse/head';
useHead({
 title: '首页 - Friday AI',
})
</script>
<template>
 <div class="space-y-8">
 <!-- Hero 区域 -->
 <section class="text-center py-12">
 <h1 class="text-4xl font-bold tracking-tight mb-4">
 Friday AI
 </h1>
 <p class="text-xl text-muted-foreground max-w-2xl mx-auto">
 AI 驱动的敏捷开发自动化系统，无缝集成飞书项目管理和 Claude Code
 </p>
 </section>
 <!-- 功能卡片 -->
 <section class="grid gap-6 md:grid-cols-3">
 <div class="rounded-lg border bg-card ">
 <h3 class="font-semibold mb-2">🤖 智能任务执行</h3>
 <p class="text-muted-foreground text-sm">
 自动监听飞书工作项，利用 AI 生成实现方案和代码
 </p>
 </div>
 <div class="rounded-lg border bg-card ">
 <h3 class="font-semibold mb-2">🔒 安全隔离</h3>
 <p class="text-muted-foreground text-sm">
 每个任务在独立 Docker 容器中执行，确保环境安全
 </p>
 </div>
 <div class="rounded-lg border bg-card ">
 <h3 class="font-semibold mb-2">👁️ 人工审核</h3>
 <p class="text-muted-foreground text-sm">
 完整的状态流转管理和人工审核机制
 </p>
 </div>
 </section>
 <!-- 快速入口 -->
 <section class="flex justify-center gap-4">
 <RouterLink
 to="/tasks"
 class="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
 >
 查看任务
 </RouterLink>
 </section>
 </div>
</template>