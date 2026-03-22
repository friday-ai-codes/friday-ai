<script setup lang="ts">
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import ChatMessageBubble from './ChatMessageBubble.vue'
import ChatWelcome from './ChatWelcome.vue'
const chatStore = useChatStore
// 滚动容器 ref
const scrollContainer = ref<HTMLElement | null>(null)
// 使用 @vueuse/core useScroll 检测滚动状态
const { arrivedState } = useScroll(scrollContainer, {
 offset: { bottom: 50 },
})
const isAtBottom = computed( => arrivedState.bottom)
const showScrollToBottom = computed( => !isAtBottom.value && chatStore.messages.length > 0)
// 滚动到底部
function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
 if (scrollContainer.value) {
 scrollContainer.value.scrollTo({
 top: scrollContainer.value.scrollHeight,
 behavior,
 })
 }
}
// 新消息/流式内容到达时自动滚动
watch(
 => [chatStore.messages.length, chatStore.streamingContent, chatStore.error],
 => {
 if (isAtBottom.value || chatStore.isStreaming || chatStore.error) {
 nextTick( => scrollToBottom(chatStore.isStreaming ? 'instant': 'smooth'))
 }
 },
)
// 选择对话时滚动到底部
watch(
 => chatStore.currentConversationId,
 => {
 nextTick( => scrollToBottom('instant'))
 },
)
</script>
<template>
 <div class="flex-1 overflow-hidden relative">
 <!-- Loading 骨架屏 -->
 <div v-if="chatStore.messagesLoading" class=" space-y-6">
 <div v-for="i in 3":key="i" class="flex gap-3":class="i % 2 === 0 ? 'flex-row-reverse': ''">
 <Skeleton class=" w-8 rounded-full shrink-0" />
 <div class="space-y-2">
 <Skeleton class=" w-48" />
 <Skeleton class=" w-64 rounded-2xl" />
 </div>
 </div>
 </div>
 <!-- 空对话欢迎页 -->
 <ChatWelcome
 v-else-if="!chatStore.hasConversation || (chatStore.messages.length === 0 && !chatStore.isStreaming)"
 />
 <!-- 消息列表 -->
 <div
 v-else
 ref="scrollContainer"
 class="h-full overflow-y-auto"
 >
 <div class="max-w-3xl mx-auto px-4 py-6 space-y-6">
 <!-- 历史消息 -->
 <ChatMessageBubble
 v-for="msg in chatStore.messages":key="msg.id":message="msg"
 />
 <!-- 流式消息（正在生成） -->
 <ChatMessageBubble
 v-if="chatStore.isStreaming":message="{
 id: 'streaming',
 role: 'assistant',
 content: '',
 created_at: new Date.toISOString,
 }":is-streaming="true":streaming-content="chatStore.streamingContent":streaming-thinking="chatStore.streamingThinking":streaming-tool-calls="chatStore.streamingToolCalls":streaming-status="chatStore.streamingStatus"
 />
 <!-- 错误提示 -->
 <div
 v-if="chatStore.error"
 class="flex items-start gap-3 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm"
 >
 <span class="icon-[lucide--alert-circle] text-lg shrink-0 mt-0.5" />
 <div class="flex-1 min-w-0">
 <p class="font-medium">
 请求失败
 </p>
 <p class="mt-1 opacity-80 break-words">
 {{ chatStore.error }}
 </p>
 </div>
 <button
 class="shrink-0 rounded hover:bg-destructive/10 transition-colors"
 @click="chatStore.error = null"
 >
 <span class="icon-[lucide--x] text-sm" />
 </button>
 </div>
 </div>
 </div>
 <!-- 回到底部按钮 -->
 <Transition
 enter-active-class="transition-all duration-200 ease-out"
 enter-from-class="opacity-0 translate-y-2"
 enter-to-class="opacity-100 translate-y-0"
 leave-active-class="transition-all duration-200 ease-in"
 leave-from-class="opacity-100 translate-y-0"
 leave-to-class="opacity-0 translate-y-2"
 >
 <Button
 v-if="showScrollToBottom"
 variant="outline"
 size="sm"
 class="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full shadow-lg gap-1 bg-background/80 backdrop-blur-sm"
 @click="scrollToBottom"
 >
 <span class="icon-[lucide--chevron-down] text-sm" />
 回到底部
 </Button>
 </Transition>
 </div>
</template>
