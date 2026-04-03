<script setup lang="ts">
const chatStore = useChatStore
const inputContent = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
async function handleSend {
 const content = inputContent.value.trim
 if (!content || chatStore.isStreaming)
 return
 if (!chatStore.currentConversationId) {
 await chatStore.createNewConversation
 if (!chatStore.currentConversationId)
 return
 }
 inputContent.value = ''
 nextTick(autoResize)
 await chatStore.sendMessage(content)
}
function handleKeydown(e: KeyboardEvent) {
 if (e.key === 'Enter' && !e.shiftKey) {
 e.preventDefault
 handleSend
 }
}
function autoResize {
 const el = textarea.value
 if (!el)
 return
 el.style.height = 'auto'
 el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}
</script>
<template>
 <div class="chat-input-wrapper">
 <div class="chat-input-container">
 <!-- 预算警告 -->
 <Transition
 enter-active-class="transition-all duration-300 ease-out"
 leave-active-class="transition-all duration-200 ease-in"
 enter-from-class="opacity-0 -translate-y-1"
 enter-to-class="opacity-100 translate-y-0"
 leave-from-class="opacity-100 translate-y-0"
 leave-to-class="opacity-0 -translate-y-1"
 >
 <div v-if="chatStore.budgetWarning" class="budget-bar">
 <span class="icon-[lucide--alert-triangle] text-xs" />
 本次对话已使用 {{ chatStore.budgetWarning }}% 预算
 </div>
 </Transition>
 <!-- 停止按钮 -->
 <div v-if="chatStore.isStreaming" class="flex justify-center pb-2">
 <button class="stop-btn" @click="chatStore.stopStreaming">
 <span class="stop-icon" />
 停止生成
 </button>
 </div>
 <!-- 输入框 -->
 <div class="input-box":class="{ 'input-box--disabled': chatStore.isStreaming }">
 <textarea
 ref="textarea"
 v-model="inputContent"
 placeholder="给 Friday 发消息..."
 class="input-textarea"
 rows="1":disabled="chatStore.isStreaming"
 @keydown="handleKeydown"
 @input="autoResize"
 />
 <button
 class="send-btn":class="{ 'send-btn--active': inputContent.trim && !chatStore.isStreaming }":disabled="!inputContent.trim || chatStore.isStreaming"
 @click="handleSend"
 >
 <span class="icon-[lucide--arrow-up] text-sm" />
 </button>
 </div>
 </div>
 </div>
</template>
<style scoped>
.chat-input-wrapper {
 padding: 1rem 1rem 1.25rem;
 background: linear-gradient(to top, hsl(210 40% 98%) 60%, hsl(210 40% 98% / 0.95) 80%, transparent);
 pointer-events: none;
}
.chat-input-wrapper > * {
 pointer-events: auto;
}
.chat-input-container {
 max-width: 48rem;
 margin: 0 auto;
}
.budget-bar {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.375rem 0.75rem;
 margin-bottom: 0.5rem;
 border-radius: 0.625rem;
 background: hsl(38 92% 50% / 0.08);
 border: 1px solid hsl(38 92% 50% / 0.2);
 color: hsl(38 80% 40%);
 font-size: 0.6875rem;
}
.stop-btn {
 display: inline-flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.375rem 0.875rem;
 border-radius: 9999px;
 font-size: 0.75rem;
 font-weight: 500;
 color: hsl(215 16% 47%);
 background: white;
 border: 1px solid hsl(214 32% 91%);
 cursor: pointer;
 transition: all 0.15s;
 box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.stop-btn:hover {
 border-color: hsl(0 72% 51% / 0.3);
 color: hsl(0 72% 51%);
 background: hsl(0 72% 51% / 0.04);
}
.stop-icon {
 width: 10px;
 height: 10px;
 border-radius: 2px;
 background: currentColor;
}
.input-box {
 display: flex;
 align-items: flex-end;
 gap: 0.5rem;
 padding: 0.625rem 0.625rem 0.625rem 1rem;
 border-radius: 1.5rem;
 border: 1px solid hsl(214 32% 88%);
 background: white;
 box-shadow:
 0 1px 3px rgba(0, 0, 0, 0.06),
 0 4px 16px rgba(0, 0, 0, 0.04),
 0 8px 32px rgba(0, 0, 0, 0.02);
 transition: all 0.2s;
}
.input-box:focus-within {
 border-color: hsl(168 76% 42% / 0.5);
 box-shadow:
 0 0 0 3px hsl(168 76% 42% / 0.08),
 0 1px 3px rgba(0, 0, 0, 0.04);
}
.input-box--disabled {
 opacity: 0.6;
}
.input-textarea {
 flex: 1;
 border: none;
 outline: none;
 resize: none;
 background: transparent;
 font-size: 0.9375rem;
 line-height: 1.5;
 color: hsl(215 28% 17%);
 max-height: 160px;
 padding: 0.125rem 0;
}
.input-textarea:placeholder {
 color: hsl(215 16% 60%);
}
.input-textarea:disabled {
 cursor: not-allowed;
}
.send-btn {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 2rem;
 height: 2rem;
 border-radius: 50%;
 border: none;
 background: hsl(214 32% 91% / 0.5);
 color: hsl(215 16% 60%);
 cursor: not-allowed;
 transition: all 0.2s;
 flex-shrink: 0;
}
.send-btn--active {
 background: hsl(168 76% 42%);
 color: white;
 cursor: pointer;
 box-shadow: 0 1px 3px rgba(20, 184, 166, 0.3);
}
.send-btn--active:hover {
 background: hsl(167 76% 36%);
}
</style>
