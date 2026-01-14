<script setup lang="ts">
// 默认布局组件
// 包含导航栏和页面容器
</script>
<template>
 <div class="min-h-screen flex flex-col">
 <!-- 顶部导航 -->
 <header class="border-b bg-card">
 <nav class="container mx-auto px-4 flex items-center justify-between">
 <div class="flex items-center gap-6">
 <RouterLink to="/" class="text-xl font-bold">
 Friday AI
 </RouterLink>
 <div class="flex items-center gap-4">
 <RouterLink
 to="/"
 class="text-muted-foreground hover:text-foreground transition-colors"
 >
 首页
 </RouterLink>
 <RouterLink
 to="/tasks"
 class="text-muted-foreground hover:text-foreground transition-colors"
 >
 任务
 </RouterLink>
 </div>
 </div>
 </nav>
 </header>
 <!-- 页面内容 -->
 <main class="flex-1 container mx-auto px-4 py-8">
 <RouterView />
 </main>
 <!-- 底部 -->
 <footer class="border-t py-6 text-center text-muted-foreground text-sm">
 <p>© {{ new Date.getFullYear }} Friday AI. All rights reserved.</p>
 </footer>
 </div>
</template>