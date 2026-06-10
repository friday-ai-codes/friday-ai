<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import { computed, ref } from 'vue'

/**
 * 首页 Skill 安装提示卡片。
 *
 * 展示在 Cursor / Claude Code 里一键安装 friday-codebase-agent Skill
 * 的三步说明；右上角可关闭，关闭状态持久化到 localStorage 不再出现。
 */

const dismissed = useLocalStorage('friday:skill-tip-dismissed', false)

// base-url 动态取当前实例地址，用户拷出来即可用
const origin = window.location.origin

const installCommand = 'npx skills add friday-ai-codes/friday-ai --skill friday-codebase-agent'
const initCommand = computed(() => `npx -y @friday-ai/mcp init --base-url ${origin} --token <你的访问令牌>`)

const copiedKey = ref<string | null>(null)

async function copy(key: string, text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    setTimeout(() => {
      if (copiedKey.value === key)
        copiedKey.value = null
    }, 2000)
  }
  catch {
    // 剪贴板不可用（非安全上下文等）时静默忽略，用户可手动选中复制
  }
}
</script>

<template>
  <section
    v-if="!dismissed"
    data-testid="skill-install-tip"
    class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 p-5 md:p-6"
  >
    <button
      type="button"
      aria-label="关闭提示"
      data-testid="skill-tip-dismiss"
      class="absolute top-3 right-3 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
      @click="dismissed = true"
    >
      <span class="icon-[lucide--x] text-base block" />
    </button>

    <div class="flex items-center gap-2.5 mb-1">
      <span class="icon-[lucide--sparkles] text-lg text-primary" />
      <h2 class="text-base font-semibold text-foreground">
        在 Cursor / Claude Code 中使用 Friday
      </h2>
    </div>
    <p class="text-sm text-muted-foreground mb-4">
      安装 friday-codebase-agent Skill，让本地 AI 助手直接调用本实例的代码索引、Graph RAG、编码计划与 PR / MR 工具。
    </p>

    <ol class="space-y-3 text-sm">
      <li class="flex flex-col gap-1.5 md:flex-row md:items-center md:gap-3">
        <span class="shrink-0 text-muted-foreground w-28">1. 安装 Skill</span>
        <code class="flex-1 min-w-0 truncate font-mono text-xs bg-muted/60 rounded-lg px-3 py-2">{{ installCommand }}</code>
        <button
          type="button"
          class="shrink-0 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          @click="copy('install', installCommand)"
        >
          <span class="icon-[lucide--copy] text-sm" />
          {{ copiedKey === 'install' ? '已复制' : '复制' }}
        </button>
      </li>
      <li class="flex flex-col gap-1.5 md:flex-row md:items-center md:gap-3">
        <span class="shrink-0 text-muted-foreground w-28">2. 创建访问令牌</span>
        <span class="flex-1 min-w-0">
          前往
          <RouterLink to="/profile" class="text-primary hover:underline">个人资料 → 访问令牌</RouterLink>
          创建（明文只显示一次）
        </span>
      </li>
      <li class="flex flex-col gap-1.5 md:flex-row md:items-center md:gap-3">
        <span class="shrink-0 text-muted-foreground w-28">3. 配置连接</span>
        <code class="flex-1 min-w-0 truncate font-mono text-xs bg-muted/60 rounded-lg px-3 py-2">{{ initCommand }}</code>
        <button
          type="button"
          class="shrink-0 inline-flex items-center gap-1 text-xs text-primary hover:underline"
          @click="copy('init', initCommand)"
        >
          <span class="icon-[lucide--copy] text-sm" />
          {{ copiedKey === 'init' ? '已复制' : '复制' }}
        </button>
      </li>
    </ol>
  </section>
</template>
