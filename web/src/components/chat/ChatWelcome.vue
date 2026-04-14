<script setup lang="ts">
const chatStore = useChatStore
// 快捷提示词
const quickPrompts = [
 { icon: 'icon-[lucide--code-2]', label: '解释这段代码', prompt: '请帮我解释项目中的核心代码逻辑' },
 { icon: 'icon-[lucide--folder-tree]', label: '查看项目结构', prompt: '请列出当前项目的文件结构，并概述各模块的作用' },
 { icon: 'icon-[lucide--search]', label: '搜索代码', prompt: '请帮我在项目中搜索相关的代码实现' },
 { icon: 'icon-[lucide--file-text]', label: '项目概览', prompt: '请给我一个当前项目的整体概览' },
]
async function handleQuickPrompt(prompt: string) {
 if (!chatStore.currentConversationId) {
 await chatStore.createNewConversation
 if (!chatStore.currentConversationId)
 return
 }
 await chatStore.sendMessage(prompt)
}
</script>
<template>
 <div class="h-full flex items-center justify-center">
 <div class="text-center max-w-lg px-4">
 <!-- Logo + 标题 -->
 <div class="mb-8">
 <div class="inline-flex rounded-2xl bg-primary/10 mb-4">
 <span class="icon-[lucide--bot] text-5xl text-primary" />
 </div>
 <h1 class="text-2xl font-bold mb-2">
 Friday AI
 </h1>
 <p class="text-sm text-muted-foreground">
 项目全知的 AI 对话助手，帮你快速了解项目知识
 </p>
 </div>
 <!-- 快捷提示词卡片 -->
 <div class="grid grid-cols-2 gap-3">
 <div
 v-for="item in quickPrompts":key="item.label"
 class="card group cursor-pointer hover:shadow-lg hover:border-primary/30 transition-all duration-200"
 @click="handleQuickPrompt(item.prompt)"
 >
 <div class="flex items-start gap-3">
 <div class=" rounded-lg bg-primary/10 shrink-0">
 <span:class="item.icon" class="text-lg text-primary" />
 </div>
 <div class="text-left">
 <p class="text-sm font-medium group-hover:text-primary transition-colors">
 {{ item.label }}
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- 提示 -->
 <p class="mt-6 text-xs text-muted-foreground/50">
 先在顶部选择项目，然后输入问题或点击上方快捷提示
 </p>
 </div>
 </div>
</template>
