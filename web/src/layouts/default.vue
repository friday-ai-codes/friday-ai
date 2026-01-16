<script setup lang="ts">
import { Toaster } from '~/components/ui/sonner'
// 导航项定义
const navItems = [
 { to: '/', label: '首页', icon: 'lucide--home' },
 { to: '/projects', label: '项目', icon: 'lucide--folder-git-2' },
 { to: '/repositories', label: '仓库', icon: 'lucide--git-branch' },
 { to: '/tasks', label: '任务', icon: 'lucide--list-checks' },
 { to: '/logs', label: '日志', icon: 'lucide--file-text' },
]
const route = useRoute
// 判断当前路由是否激活
function isActive(path: string) {
 if (path === '/') {
 return route.path === '/'
 }
 return route.path.startsWith(path)
}
</script>
<template>
 <div class="min-h-screen flex flex-col bg-background">
 <!-- 顶部导航 -->
 <header class="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
 <nav class="container mx-auto px-4 flex items-center justify-between">
 <div class="flex items-center gap-8">
 <!-- Logo -->
 <RouterLink to="/" class="flex items-center gap-2 text-xl font-bold text-primary">
 <span class="icon-[lucide--bot] text-2xl" />
 <span>Friday AI</span>
 </RouterLink>
 <!-- 导航链接 -->
 <div class="hidden md:flex items-center gap-1">
 <RouterLink
 v-for="item in navItems":key="item.to":to="item.to"
 class="flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors":class="[
 isActive(item.to)
 ? 'bg-primary/10 text-primary': 'text-muted-foreground hover:text-foreground hover:bg-accent/50',
 ]"
 >
 <span class="text-lg":class="[`icon-[${item.icon}]`]" />
 <span>{{ item.label }}</span>
 </RouterLink>
 </div>
 </div>
 <!-- 右侧操作区 -->
 <div class="flex items-center gap-4">
 <!-- 状态指示器 -->
 <div class="hidden sm:flex items-center gap-2 text-sm text-muted-foreground">
 <span class="w-2 rounded-full bg-green-500" />
 <span>在线</span>
 </div>
 </div>
 </nav>
 </header>
 <!-- 页面内容 -->
 <main class="flex-1 container mx-auto px-4 py-6">
 <RouterView />
 </main>
 <!-- 底部 -->
 <footer class="border-t py-6">
 <div class="container mx-auto px-4 flex items-center justify-between text-sm text-muted-foreground">
 <p>© {{ new Date.getFullYear }} Friday AI. All rights reserved.</p>
 <div class="flex items-center gap-4">
 <a href="https://github.com" target="_blank" class="hover:text-foreground transition-colors flex items-center gap-1">
 <span class="icon-[lucide--github]" />
 <span>GitHub</span>
 </a>
 <a href="/docs" class="hover:text-foreground transition-colors flex items-center gap-1">
 <span class="icon-[lucide--book-open]" />
 <span>API 文档</span>
 </a>
 </div>
 </div>
 </footer>
 <!-- Toast 通知 -->
 <Toaster rich-colors position="top-right" />
 </div>
</template>
