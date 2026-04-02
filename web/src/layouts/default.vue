<script setup lang="ts">
import AppSidebar from '~/components/layout/AppSidebar.vue'
import ChatHeader from '~/components/chat/ChatHeader.vue'
import ChatInput from '~/components/chat/ChatInput.vue'
import ChatMessageArea from '~/components/chat/ChatMessageArea.vue'
import ChatSidebar from '~/components/chat/ChatSidebar.vue'
import { Toaster } from '~/components/ui/sonner'
import { useAppMode } from '~/composables/useAppMode'
const { mode, chatInitialized } = useAppMode
// WebSocket 实时监控
const { status, connect } = useRunnerMonitor
onMounted( => {
 connect
})
// Chat 模式懒加载：首次进入 chat 模式时初始化数据
const chatStore = useChatStore
const projectsStore = useProjectsStore
watch(mode, async (m) => {
 if (m === 'chat' && !chatInitialized.value) {
 chatInitialized.value = true
 await Promise.all([
 chatStore.fetchConversations,
 projectsStore.fetchProjects,
 ])
 }
}, { immediate: true })
// 从 route.meta 获取页面标题
const route = useRoute
const pageTitle = computed( => {
 const meta = route.meta as { title?: string }
 return meta.title || ''
})
</script>
<template>
 <div class="min-h-screen flex bg-background">
 <!-- ==================== 侧边栏区域（直接切换，不用 Transition） ==================== -->
 <AppSidebar v-if="mode === 'friday'" />
 <ChatSidebar v-else />
 <!-- ==================== 主内容区域 ==================== -->
 <Transition name="mode-content" mode="out-in">
 <!-- Friday 工作台模式 -->
 <div v-if="mode === 'friday'" key="content-friday" class="flex-1 flex flex-col min-w-0 bg-gray-50">
 <!-- Sub2API 风格顶栏 — 玻璃效果 -->
 <header class="header-glass sticky top-0 z-40 ">
 <div class="flex h-full items-center justify-between px-6">
 <div>
 <h1 v-if="pageTitle" class="text-lg font-semibold text-foreground">
 {{ pageTitle }}
 </h1>
 </div>
 <div class="flex items-center gap-3">
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
 'text-emerald-600': status === 'connected',
 'text-amber-600': status === 'connecting' || status === 'reconnecting',
 'text-red-600': status === 'disconnected',
 }"
 >
 {{ status === 'connected' ? '已连接': status === 'disconnected' ? '已断开': '重连中...' }}
 </span>
 </div>
 </div>
 </div>
 </header>
 <main class="flex-1 bg-mesh-gradient">
 <RouterView />
 </main>
 </div>
 <!-- Chat AI 对话模式 -->
 <div v-else key="content-chat" class="flex-1 flex flex-col min-w-0">
 <ChatHeader />
 <ChatMessageArea />
 <ChatInput />
 </div>
 </Transition>
 </div>
 <!-- Toast 通知 -->
 <Toaster rich-colors position="top-right" />
</template>
<style scoped>
/* 主内容区切换 — 平滑淡入 + 微位移 */
.mode-content-enter-active {
 transition: opacity 0.3s ease, transform 0.3s ease;
}
.mode-content-leave-active {
 transition: opacity 0.15s ease;
}
.mode-content-enter-from {
 opacity: 0;
 transform: translateY(8px);
}
.mode-content-leave-to {
 opacity: 0;
}
</style>
