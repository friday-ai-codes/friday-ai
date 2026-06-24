<script setup lang="ts">
import starBurstAnimation from '~/assets/lottie/starBurst'
import { useHoverLottie } from '~/composables/useMotion'

const REPO_URL = 'https://github.com/friday-ai-codes/friday-ai'

const starEl = ref<HTMLElement | null>(null)
const { play } = useHoverLottie(starEl, starBurstAnimation)
</script>

<template>
  <a
    :href="REPO_URL"
    target="_blank"
    rel="noopener noreferrer"
    class="group inline-flex items-center gap-1.5 h-9 rounded-full border border-border/60 bg-card/60 pl-1.5 pr-3 text-sm font-medium text-foreground! transition-colors hover:border-border hover:bg-card"
    aria-label="在 GitHub 上给个 Star"
    @mouseenter="play"
  >
    <!-- 图标位：默认 GitHub logo，hover 时淡出缩小并过渡成 star lottie -->
    <span class="relative flex h-6 w-6 shrink-0 items-center justify-center">
      <span
        class="icon-[mdi--github] absolute text-[22px] transition-all duration-300 ease-out group-hover:scale-50 group-hover:-rotate-45 group-hover:opacity-0"
      />
      <span
        ref="starEl"
        class="absolute h-6 w-6 scale-50 opacity-0 transition-all duration-300 ease-out group-hover:scale-100 group-hover:opacity-100"
      />
    </span>
    <span>给个 Star</span>
  </a>
</template>
