<script setup lang="ts">
import ChatHeader from '~/components/chat/ChatHeader.vue'
import ChatInput from '~/components/chat/ChatInput.vue'
import ChatMessageArea from '~/components/chat/ChatMessageArea.vue'
import AppSidebar from '~/components/layout/AppSidebar.vue'
import SystemHealthPopover from '~/components/layout/SystemHealthPopover.vue'
import { Toaster } from '~/components/ui/sonner'
import { useAppMode } from '~/composables/useAppMode'
const { mode, chatInitialized, setMode } = useAppMode
// WebSocket 实时监控：保留自动连接逻辑；状态展示由 SystemHealthPopover 聚合
const { connect } = useRunnerMonitor
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
 await chatStore.restoreFromURL
 if (chatStore.notificationsEnabled)
 chatStore.requestNotificationPermission
 }
}, { immediate: true })
const route = useRoute
const displayMode = computed( => (route.path === '/' ? mode.value: 'friday'))
watch(
 => route.path,
 (path) => {
 if (path !== '/' && mode.value === 'chat') {
 setMode('friday')
 }
 },
 { immediate: true },
)
// 从 route.meta 获取页面标题
const pageTitle = computed( => {
 const meta = route.meta as { title?: string }
 return meta.title || ''
})
</script>
<template>
 <div class="min-h-screen flex bg-background">
 <!-- 统一侧边栏 -->
 <AppSidebar />
 <!-- 主内容区域 -->
 <Transition name="mode-content" mode="out-in">
 <!-- 工作台模式 -->
 <div v-if="displayMode === 'friday'" key="content-friday" class="flex-1 flex flex-col min-w-0 bg-gray-50">
 <header class="header-glass sticky top-0 z-40 ">
 <div class="flex h-full items-center justify-between px-6">
 <div>
 <h1 v-if="pageTitle" class="text-lg font-semibold text-foreground">
 {{ pageTitle }}
 </h1>
 </div>
 <div class="flex items-center gap-3">
 <SystemHealthPopover />
 </div>
 </div>
 </header>
 <main class="flex-1 bg-mesh-gradient">
 <RouterView />
 </main>
 </div>
 <!-- Chat 对话模式 -->
 <div v-else key="content-chat" class="flex-1 flex flex-col min-w-0">
 <ChatHeader />
 <div class="flex-1 min- relative">
 <ChatMessageArea />
 <ChatInput class="chat-input-float" />
 </div>
 </div>
 </Transition>
 </div>
 <Toaster rich-colors position="top-right" />
</template>
<style scoped>
.mode-content-enter-active {
 transition:
 opacity 0.3s ease,
 transform 0.3s ease;
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
.chat-input-float {
 position: absolute;
 bottom: 0;
 left: 0;
 right: 0;
 z-index: 10;
 pointer-events: none;
}
</style>
