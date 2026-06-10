<script setup lang="ts">
import { gsap } from 'gsap'
import { ref } from 'vue'

export interface QuickAction {
  icon: string
  title: string
  description: string
  link: string
  iconBg: string
}

defineProps<{
  actions: QuickAction[]
}>()

// 快捷操作按钮弹性错拍入场
const rootEl = ref<HTMLElement | null>(null)
useGsapReveal(rootEl, () => {
  gsap.from('.quick-action', {
    y: 10,
    scale: 0.92,
    autoAlpha: 0,
    duration: 0.4,
    stagger: 0.05,
    delay: 0.35,
    ease: 'back.out(1.6)',
    clearProps: 'all',
  })
})
</script>

<template>
  <section ref="rootEl" class="flex flex-wrap gap-3">
    <RouterLink
      v-for="action in actions"
      :key="action.title"
      :to="action.link"
      class="quick-action group inline-flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-card/80 backdrop-blur-sm border border-border/50 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all duration-200"
    >
      <span class="text-base text-muted-foreground group-hover:text-primary transition-colors" :class="`icon-[${action.icon}]`" />
      <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ action.title }}</span>
    </RouterLink>
  </section>
</template>
