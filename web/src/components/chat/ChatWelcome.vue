<script setup lang="ts">
const chatStore = useChatStore()

// 快捷提示词
const quickPrompts = [
  { icon: 'icon-[lucide--code-2]', label: '解释这段代码', prompt: '请帮我解释空间中的核心代码逻辑' },
  { icon: 'icon-[lucide--folder-tree]', label: '查看空间结构', prompt: '请列出当前空间的文件结构，并概述各模块的作用' },
  { icon: 'icon-[lucide--search]', label: '搜索代码', prompt: '请帮我在空间中搜索相关的代码实现' },
  { icon: 'icon-[lucide--file-text]', label: '空间概览', prompt: '请给我一个当前空间的整体概览' },
]

async function handleQuickPrompt(prompt: string) {
  await chatStore.sendMessage(prompt)
}
</script>

<template>
  <div class="h-full flex items-center justify-center">
    <div class="text-center max-w-lg px-4">
      <!-- Logo + 标题 -->
      <div class="mb-8">
        <img
          src="/logo-mark.svg"
          alt="Friday"
          class="mx-auto w-16 h-16 mb-4"
        >
        <h1 class="sr-only">
          Friday AI
        </h1>
        <img
          src="/logo-wordmark.svg"
          alt="friday"
          aria-hidden="true"
          class="mx-auto h-6 w-auto mb-2"
        >
        <p class="text-sm text-muted-foreground">
          空间全知的 AI 对话助手，帮你快速了解空间知识
        </p>
      </div>

      <!-- 快捷提示词卡片 -->
      <div class="grid grid-cols-2 gap-3">
        <div
          v-for="item in quickPrompts"
          :key="item.label"
          class="card group cursor-pointer p-4 hover:shadow-lg hover:border-primary/30 transition-all duration-200"
          @click="handleQuickPrompt(item.prompt)"
        >
          <div class="flex items-start gap-3">
            <div class="p-2 rounded-lg bg-primary/10 shrink-0">
              <span :class="item.icon" class="text-lg text-primary" />
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
        先在顶部选择空间，然后输入问题或点击上方快捷提示
      </p>
    </div>
  </div>
</template>
