<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import ChatMessageBubble from './ChatMessageBubble.vue'
import ChatWelcome from './ChatWelcome.vue'
const chatStore = useChatStore
const scrollContainer = ref<HTMLElement | null>(null)
const { arrivedState } = useScroll(scrollContainer, { offset: { bottom: 50 } })
const isAtBottom = computed( => arrivedState.bottom)
const showScrollToBottom = computed( => !isAtBottom.value && chatStore.messages.length > 0)
function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
 if (scrollContainer.value) {
 scrollContainer.value.scrollTo({ top: scrollContainer.value.scrollHeight, behavior })
 }
}
watch(
 => [chatStore.messages.length, chatStore.streamingContent, chatStore.deepAnalysisLogs.length, chatStore.error],
 => {
 if (isAtBottom.value || chatStore.isStreaming || chatStore.error)
 nextTick( => scrollToBottom(chatStore.isStreaming ? 'instant': 'smooth'))
 },
)
watch(
 => chatStore.currentConversationId,
 => nextTick( => scrollToBottom('instant')),
)
</script>
<template>
 <div class="flex-1 overflow-hidden relative">
 <!-- Loading 骨架屏 -->
 <div v-if="chatStore.messagesLoading" class="max-w-3xl mx-auto px-6 py-8 space-y-6">
 <div v-for="i in 3":key="i">
 <div v-if="i % 2 === 0" class="flex justify-end">
 <Skeleton class=" w-52 rounded-2xl" />
 </div>
 <div v-else class="space-y-2">
 <Skeleton class=" w-96" />
 <Skeleton class=" w-72" />
 <Skeleton class=" w-48" />
 </div>
 </div>
 </div>
 <!-- 空对话欢迎页 -->
 <ChatWelcome
 v-else-if="!chatStore.hasConversation || (chatStore.messages.length === 0 && !chatStore.isStreaming)"
 />
 <!-- 消息列表 -->
 <div v-else ref="scrollContainer" class="h-full overflow-y-auto">
 <div class="max-w-3xl mx-auto px-6 pt-8 pb-28 space-y-7">
 <ChatMessageBubble
 v-for="msg in chatStore.messages":key="msg.id":message="msg"
 />
 <!-- 流式消息 -->
 <ChatMessageBubble
 v-if="chatStore.isStreaming":message="{
 id: 'streaming',
 role: 'assistant',
 content: '',
 created_at: new Date.toISOString,
 }":is-streaming="true":streaming-content="chatStore.streamingContent":streaming-thinking="chatStore.streamingThinking":streaming-tool-calls="chatStore.streamingToolCalls":streaming-status="chatStore.streamingStatus":streaming-narrations="chatStore.streamingNarrations":streaming-pending-text="chatStore.streamingPendingText":deep-analysis-logs="chatStore.deepAnalysisLogs"
 />
 <!-- 错误提示 -->
 <div v-if="chatStore.error" class="error-card">
 <div class="error-icon">
 <span class="icon-[lucide--alert-circle] text-sm" />
 </div>
 <div class="flex-1 min-w-0">
 <p class="text-[13px] font-medium text-destructive">
 请求失败
 </p>
 <p class="text-xs text-destructive/70 mt-0.5">
 {{ chatStore.error }}
 </p>
 <div v-if="chatStore.lastFailedContent" class="mt-2.5 flex items-center gap-2">
 <Button
 variant="outline"
 size="sm"
 class=" text-xs text-destructive border-destructive/20 hover:bg-destructive/5 gap-1.5 rounded-lg":disabled="chatStore.isStreaming"
 @click="chatStore.retryLastMessage"
 >
 <span class="icon-[lucide--refresh-cw] text-[10px]" />
 重试
 </Button>
 </div>
 </div>
 <button
 class="shrink-0 rounded-md hover:bg-destructive/8 transition-colors text-destructive/40 hover:text-destructive"
 @click="chatStore.error = null; chatStore.lastFailedContent = null"
 >
 <span class="icon-[lucide--x] text-xs" />
 </button>
 </div>
 </div>
 </div>
 <!-- 回到底部 -->
 <Transition
 enter-active-class="transition-all duration-200 ease-out"
 enter-from-class="opacity-0 translate-y-2"
 enter-to-class="opacity-100 translate-y-0"
 leave-active-class="transition-all duration-150 ease-in"
 leave-from-class="opacity-100 translate-y-0"
 leave-to-class="opacity-0 translate-y-2"
 >
 <button
 v-if="showScrollToBottom"
 class="scroll-btn"
 @click="scrollToBottom"
 >
 <span class="icon-[lucide--chevron-down] text-sm" />
 </button>
 </Transition>
 </div>
</template>
<style scoped>
.error-card {
 display: flex;
 align-items: flex-start;
 gap: 0.625rem;
 padding: 0.75rem 1rem;
 border-radius: 0.75rem;
 background: hsl(0 72% 51% / 0.04);
 border: 1px solid hsl(0 72% 51% / 0.1);
}
.error-icon {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 1.5rem;
 height: 1.5rem;
 border-radius: 50%;
 background: hsl(0 72% 51% / 0.08);
 color: hsl(0 72% 51%);
 flex-shrink: 0;
 margin-top: 0.0625rem;
}
.scroll-btn {
 position: absolute;
 bottom: 5rem;
 left: 50%;
 transform: translateX(-50%);
 display: flex;
 align-items: center;
 justify-content: center;
 width: 2rem;
 height: 2rem;
 border-radius: 50%;
 background: white;
 border: 1px solid hsl(214 32% 91%);
 color: hsl(215 16% 47%);
 cursor: pointer;
 box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
 transition: all 0.15s;
}
.scroll-btn:hover {
 border-color: hsl(168 76% 42% / 0.3);
 color: hsl(168 76% 42%);
 box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
</style>
