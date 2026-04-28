<route lang="yaml">
meta:
 title: AI 对话
</route>
<script setup lang="ts">
import ChatHeader from '~/components/chat/ChatHeader.vue'
import ChatMessageArea from '~/components/chat/ChatMessageArea.vue'
import ChatInput from '~/components/chat/ChatInput.vue'
const chatStore = useChatStore
const projectsStore = useProjectsStore
// Chat 数据懒加载：首次进入 /chat 时初始化
onMounted(async => {
 await Promise.all([
 chatStore.fetchConversations,
 projectsStore.fetchProjects,
 ])
 await chatStore.restoreFromURL
 if (chatStore.notificationsEnabled)
 chatStore.requestNotificationPermission
})
</script>
<template>
 <div class="flex-1 flex flex-col min-w-0 h-full">
 <!--
 UX 重设计：chat 路径 Provider/模型选择已折叠到 ChatInput
 底部 model-selector。ChatHeader 不再消费 conversation-id / current-credential-id
 / current-model / message-count / waiting-for-input；@pin-confirmed listener
 迁移到 ChatInput，且参数升级为 (credentialId, model) 双字段，路由到
 chatStore.patchConversationProviderAndModel（单次 PATCH 双字段，避免中间态）。:resolved-provider 暂不接（继承自；ChatHeader 默认 null + v-if 兜底）。
 -->
 <ChatHeader />
 <div class="flex-1 min- relative">
 <ChatMessageArea />
 <ChatInput
 class="chat-input-float"
 @pin-confirmed="chatStore.patchConversationProviderAndModel"
 />
 </div>
 </div>
</template>
<style scoped>
.chat-input-float {
 position: absolute;
 bottom: 0;
 left: 0;
 right: 0;
 z-index: 10;
 pointer-events: none;
}
</style>
