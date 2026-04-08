<script setup lang="ts">
import type { Model } from '~/api/chat'
import { getModels } from '~/api/chat'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { extractFirstFeishuDocId } from '~/composables/useFeishuDocDetect'
const chatStore = useChatStore
const inputContent = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const models = ref<Model>
const showModelMenu = ref(false)
const modelMenuRef = ref<HTMLElement | null>(null)
onMounted(async => {
 try {
 const resp = await getModels({})
 models.value = resp.models
 }
 catch {
 // 静默处理
 }
})
onClickOutside(modelMenuRef, => {
 showModelMenu.value = false
})
const currentModelLabel = computed( => {
 if (!chatStore.selectedModel || chatStore.selectedModel === '__default__')
 return '系统默认'
 const found = models.value.find(m => m.id === chatStore.selectedModel)
 return found?.name || found?.id || chatStore.selectedModel
})
function selectModel(id: string) {
 chatStore.selectedModel = id
 showModelMenu.value = false
}
async function handleSend {
 const content = inputContent.value.trim
 if (!content || chatStore.isStreaming)
 return
 if (!chatStore.currentConversationId) {
 await chatStore.createNewConversation
 if (!chatStore.currentConversationId)
 return
 }
 const feishuDocId = extractFirstFeishuDocId(content)
 inputContent.value = ''
 nextTick(autoResize)
 await chatStore.sendMessage(content, feishuDocId ?? undefined)
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
 el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}
function toggleDeepAnalysis {
 chatStore.forceDeepAnalysis = !chatStore.forceDeepAnalysis
}
function toggleNotifications {
 void chatStore.toggleNotifications(!chatStore.notificationsEnabled)
}
</script>
<template>
 <div class="chat-input-dock">
 <div class="chat-input-center">
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
 <!-- 输入卡片 -->
 <div class="input-card":class="{ 'input-card--disabled': chatStore.isStreaming }">
 <!-- 上层：文本输入 -->
 <textarea
 ref="textarea"
 v-model="inputContent"
 placeholder="给 Friday 发消息..."
 class="input-textarea"
 rows="1":disabled="chatStore.isStreaming"
 @keydown="handleKeydown"
 @input="autoResize"
 />
 <!-- 下层：工具栏 -->
 <div class="input-toolbar">
 <!-- 左侧工具 -->
 <div class="toolbar-left">
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="toolbar-btn":class="{ 'toolbar-btn--active': chatStore.forceDeepAnalysis }"
 @click="toggleDeepAnalysis"
 >
 <span class="icon-[lucide--scan-search] text-[15px]" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ chatStore.forceDeepAnalysis ? '深度分析已开启 · Runner + Claude Code': '点击开启深度分析' }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="toolbar-btn":class="{ 'toolbar-btn--active': chatStore.notificationsEnabled }"
 @click="toggleNotifications"
 >
 <span:class="chatStore.notificationsEnabled ? 'icon-[lucide--bell-ring]': 'icon-[lucide--bell-off]'" class="text-[15px]" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ chatStore.notificationsEnabled ? '浏览器通知已开启': '点击开启浏览器通知' }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 <!-- 右侧：模型选择 + 发送 -->
 <div class="toolbar-right">
 <!-- 模型选择器 -->
 <div ref="modelMenuRef" class="relative">
 <button class="model-selector" @click="showModelMenu = !showModelMenu">
 <span class="model-label">{{ currentModelLabel }}</span>
 <span class="icon-[lucide--chevron-down] text-[11px] transition-transform":class="{ 'rotate-180': showModelMenu }" />
 </button>
 <Transition
 enter-active-class="transition-all duration-150 ease-out"
 leave-active-class="transition-all duration-100 ease-in"
 enter-from-class="opacity-0 translate-y-1 scale-95"
 enter-to-class="opacity-100 translate-y-0 scale-100"
 leave-from-class="opacity-100 translate-y-0 scale-100"
 leave-to-class="opacity-0 translate-y-1 scale-95"
 >
 <div v-if="showModelMenu" class="model-menu">
 <button
 class="model-menu-item":class="{ 'model-menu-item--active': chatStore.selectedModel === '__default__' }"
 @click="selectModel('__default__')"
 >
 <span>系统默认</span>
 <span v-if="chatStore.selectedModel === '__default__'" class="icon-[lucide--check] text-xs text-primary" />
 </button>
 <button
 v-for="model in models":key="model.id"
 class="model-menu-item":class="{ 'model-menu-item--active': chatStore.selectedModel === model.id }"
 @click="selectModel(model.id)"
 >
 <span>{{ model.name || model.id }}</span>
 <span v-if="chatStore.selectedModel === model.id" class="icon-[lucide--check] text-xs text-primary" />
 </button>
 </div>
 </Transition>
 </div>
 <!-- 发送按钮 -->
 <button
 class="send-btn":class="{ 'send-btn--active': inputContent.trim && !chatStore.isStreaming }":disabled="!inputContent.trim || chatStore.isStreaming"
 @click="handleSend"
 >
 <span class="icon-[lucide--arrow-up] text-sm" />
 </button>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
<style scoped>
.chat-input-dock {
 padding: 0 1rem 1.25rem;
 background: linear-gradient(
 to top,
 hsl(210 40% 98%) 60%,
 hsl(210 40% 98% / 0.95) 75%,
 hsl(210 40% 98% / 0) 100%
 );
 pointer-events: none;
}
.chat-input-dock > * {
 pointer-events: auto;
}
.chat-input-center {
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
/* ======== 输入卡片 ======== */
.input-card {
 border: 1px solid hsl(214 32% 88%);
 border-radius: 1.25rem;
 background: white;
 box-shadow:
 0 1px 3px rgba(0, 0, 0, 0.06),
 0 4px 16px rgba(0, 0, 0, 0.04),
 0 8px 32px rgba(0, 0, 0, 0.02);
 transition: border-color 0.2s, box-shadow 0.2s;
 overflow: hidden;
}
.input-card:focus-within {
 border-color: hsl(168 76% 42% / 0.5);
 box-shadow:
 0 0 0 3px hsl(168 76% 42% / 0.06),
 0 1px 3px rgba(0, 0, 0, 0.06),
 0 4px 16px rgba(0, 0, 0, 0.04);
}
.input-card--disabled {
 opacity: 0.6;
}
.input-textarea {
 display: block;
 width: 100%;
 border: none;
 outline: none;
 resize: none;
 background: transparent;
 font-size: 0.9375rem;
 line-height: 1.6;
 color: hsl(215 28% 17%);
 max-height: 200px;
 padding: 0.875rem 1rem 0.25rem;
}
.input-textarea:placeholder {
 color: hsl(215 16% 60%);
}
.input-textarea:disabled {
 cursor: not-allowed;
}
/* ======== 工具栏 ======== */
.input-toolbar {
 display: flex;
 align-items: center;
 justify-content: space-between;
 padding: 0.375rem 0.5rem 0.5rem;
}
.toolbar-left {
 display: flex;
 align-items: center;
 gap: 0.125rem;
}
.toolbar-right {
 display: flex;
 align-items: center;
 gap: 0.375rem;
}
.toolbar-btn {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 2rem;
 height: 2rem;
 border-radius: 0.5rem;
 border: none;
 background: transparent;
 color: hsl(215 16% 60%);
 cursor: pointer;
 transition: all 0.15s;
}
.toolbar-btn:hover {
 background: hsl(210 40% 96%);
 color: hsl(215 28% 30%);
}
.toolbar-btn--active {
 color: hsl(168 76% 42%);
 background: hsl(168 76% 42% / 0.08);
}
.toolbar-btn--active:hover {
 background: hsl(168 76% 42% / 0.14);
 color: hsl(167 76% 36%);
}
/* ======== 模型选择器 ======== */
.model-selector {
 display: inline-flex;
 align-items: center;
 gap: 0.25rem;
 padding: 0.25rem 0.625rem;
 border-radius: 0.5rem;
 border: none;
 background: transparent;
 color: hsl(215 16% 47%);
 font-size: 0.8125rem;
 cursor: pointer;
 transition: all 0.15s;
 white-space: nowrap;
}
.model-selector:hover {
 background: hsl(210 40% 96%);
 color: hsl(215 28% 17%);
}
.model-label {
 max-width: 10rem;
 overflow: hidden;
 text-overflow: ellipsis;
}
.model-menu {
 position: absolute;
 bottom: calc(100% + 0.375rem);
 right: 0;
 min-width: 12rem;
 max-height: 16rem;
 overflow-y: auto;
 padding: 0.25rem;
 border-radius: 0.75rem;
 border: 1px solid hsl(214 32% 91%);
 background: white;
 box-shadow:
 0 4px 16px rgba(0, 0, 0, 0.08),
 0 8px 32px rgba(0, 0, 0, 0.04);
 z-index: 50;
}
.model-menu-item {
 display: flex;
 align-items: center;
 justify-content: space-between;
 width: 100%;
 padding: 0.5rem 0.75rem;
 border-radius: 0.5rem;
 border: none;
 background: transparent;
 color: hsl(215 28% 17%);
 font-size: 0.8125rem;
 text-align: left;
 cursor: pointer;
 transition: background 0.1s;
}
.model-menu-item:hover {
 background: hsl(210 40% 96%);
}
.model-menu-item--active {
 color: hsl(168 76% 42%);
}
/* ======== 发送按钮 ======== */
.send-btn {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 2rem;
 height: 2rem;
 border-radius: 0.5rem;
 border: none;
 background: hsl(214 32% 91% / 0.5);
 color: hsl(215 16% 60%);
 cursor: not-allowed;
 transition: all 0.15s;
 flex-shrink: 0;
}
.send-btn--active {
 background: hsl(168 76% 42%);
 color: white;
 cursor: pointer;
 box-shadow: 0 1px 3px hsl(168 76% 42% / 0.3);
}
.send-btn--active:hover {
 background: hsl(167 76% 36%);
}
</style>
