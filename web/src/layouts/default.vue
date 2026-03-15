<script setup lang="ts">
import { Toaster } from '~/components/ui/sonner'
import AppSidebar from '~/components/layout/AppSidebar.vue'
// WebSocket 实时监控
const { status, connect } = useRunnerMonitor
onMounted( => {
 connect
})
</script>
<template>
 <div class="min-h-screen flex bg-background">
 <!-- 侧边栏 -->
 <AppSidebar />
 <!-- 主内容区 -->
 <div class="flex-1 flex flex-col min-w-0">
 <!-- 精简顶栏（仅状态指示器） -->
 <header class="sticky top-0 z-40 border-b border-border/40 bg-background/80 backdrop-blur-xl flex items-center justify-end px-6 gap-4">
 <!-- WebSocket 连接状态指示器 -->
 <div
 class="flex items-center gap-2 px-3 py-1.5 rounded-full cursor-pointer transition-colors duration-300":class="{
 'bg-emerald-500/10 border border-emerald-500/20': status === 'connected',
 'bg-amber-500/10 border border-amber-500/20': status === 'connecting' || status === 'reconnecting',
 'bg-red-500/10 border border-red-500/20': status === 'disconnected',
 }"
 @click="status === 'disconnected' && connect"
 >
 <span class="relative flex w-2">
 <span v-if="status === 'connected'" class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
 <span
 class="relative inline-flex rounded-full w-2":class="{
 'bg-emerald-500': status === 'connected',
 'bg-amber-500 animate-pulse': status === 'connecting' || status === 'reconnecting',
 'bg-red-500': status === 'disconnected',
 }"
 />
 </span>
 <span
 class="text-sm font-medium":class="{
 'text-emerald-600 dark:text-emerald-400': status === 'connected',
 'text-amber-600 dark:text-amber-400': status === 'connecting' || status === 'reconnecting',
 'text-red-600 dark:text-red-400': status === 'disconnected',
 }"
 >
 {{ status === 'connected' ? '已连接': status === 'disconnected' ? '已断开': '重连中...' }}
 </span>
 </div>
 </header>
 <!-- 页面内容 -->
 <main class="flex-1 ">
 <RouterView />
 </main>
 </div>
 </div>
 <!-- Toast 通知 -->
 <Toaster rich-colors position="top-right" />
</template>
