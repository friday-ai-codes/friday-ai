<script setup lang="ts">
import { Toaster } from '~/components/ui/sonner'
// 导航项定义
const navItems = [
 { to: '/', label: '首页', icon: 'lucide--home' },
 { to: '/projects', label: '项目', icon: 'lucide--folder-git-2' },
 { to: '/repositories', label: '仓库', icon: 'lucide--git-branch' },
 { to: '/tasks', label: '任务', icon: 'lucide--list-checks' },
 { to: '/logs', label: '日志', icon: 'lucide--file-text' },
 { to: '/settings', label: '设置', icon: 'lucide--settings' },
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
 <header class="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
 <nav class="container mx-auto px-4 flex items-center justify-between">
 <div class="flex items-center gap-8">
 <!-- Logo -->
 <RouterLink to="/" class="group flex items-center gap-2.5 text-xl font-bold">
 <div class="relative">
 <div class="absolute inset-0 bg-gradient-to-br from-primary to-primary/50 rounded-lg blur-md opacity-50 group-hover:opacity-75 transition-opacity" />
 <div class="relative .5 rounded-lg bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center">
 <span class="icon-[lucide--bot] text-xl text-white" />
 </div>
 </div>
 <span class="bg-gradient-to-r from-primary to-primary/70 bg-clip-text text-transparent">Friday AI</span>
 </RouterLink>
 <!-- 导航链接 -->
 <div class="hidden md:flex items-center gap-1">
 <RouterLink
 v-for="item in navItems":key="item.to":to="item.to"
 class="relative flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200":class="[
 isActive(item.to)
 ? 'text-primary': 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
 ]"
 >
 <!-- 激活指示器 -->
 <div
 v-if="isActive(item.to)"
 class="absolute inset-0 bg-gradient-to-r from-primary/10 to-primary/5 rounded-lg"
 />
 <span class="relative text-lg":class="[`icon-[${item.icon}]`]" />
 <span class="relative">{{ item.label }}</span>
 </RouterLink>
 </div>
 </div>
 <!-- 右侧操作区 -->
 <div class="flex items-center gap-4">
 <!-- 状态指示器 -->
 <div class="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
 <span class="relative flex w-2">
 <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
 <span class="relative inline-flex rounded-full w-2 bg-emerald-500" />
 </span>
 <span class="text-sm text-emerald-600 font-medium">在线</span>
 </div>
 </div>
 </nav>
 </header>
 <!-- 页面内容 -->
 <main class="flex-1 container mx-auto px-4 py-8">
 <RouterView />
 </main>
 <!-- 底部 -->
 <footer class="border-t border-border/40 py-6 bg-muted/30">
 <div class="container mx-auto px-4 flex items-center justify-between text-sm text-muted-foreground">
 <p class="flex items-center gap-2">
 <span class="icon-[lucide--copyright] text-base" />
 <span>{{ new Date.getFullYear }} Friday AI. All rights reserved.</span>
 </p>
 <div class="flex items-center gap-6">
 <a
 href="https://github.com"
 target="_blank"
 class="group flex items-center gap-1.5 hover:text-foreground transition-colors"
 >
 <span class="icon-[lucide--github] text-base group-hover:scale-110 transition-transform" />
 <span>GitHub</span>
 </a>
 <a
 href="/docs"
 class="group flex items-center gap-1.5 hover:text-foreground transition-colors"
 >
 <span class="icon-[lucide--book-open] text-base group-hover:scale-110 transition-transform" />
 <span>API 文档</span>
 </a>
 </div>
 </div>
 </footer>
 <!-- Toast 通知 -->
 <Toaster rich-colors position="top-right" />
 </div>
</template>
