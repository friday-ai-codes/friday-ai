<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
export interface NavSection {
 id: string
 label: string
 icon?: string
}
const props = defineProps<{
 sections: NavSection
}>
const activeSection = ref<string>(props.sections[0]?.id ?? '')
let observer: IntersectionObserver | null = null
onMounted( => {
 observer = new IntersectionObserver(
 (entries) => {
 const visible = entries
 .filter(e => e.isIntersecting)
 .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
 if (visible.length > 0) {
 activeSection.value = visible[0].target.id
 }
 },
 {
 rootMargin: '-15% 0px -55% 0px',
 threshold: [0, 0.25, 0.5, 0.75, 1],
 },
 )
 props.sections.forEach((section) => {
 const el = document.getElementById(section.id)
 if (el) observer?.observe(el)
 })
})
onUnmounted( => {
 observer?.disconnect
})
function scrollTo(id: string) {
 const el = document.getElementById(id)
 if (!el) return
 const offset = 88
 const top = el.getBoundingClientRect.top + window.scrollY - offset
 window.scrollTo({ top, behavior: 'smooth' })
}
</script>
<template>
 <div class="flex gap-8">
 <!-- 左侧导航 -->
 <aside class="hidden md:block w-44 shrink-0">
 <nav class="sticky top-22 space-y-0.5">
 <button
 v-for="section in sections":key="section.id"
 class="w-full text-left px-3 py-1.5 rounded-md text-sm transition-colors":class="activeSection === section.id
 ? 'bg-primary/10 text-primary font-medium': 'text-muted-foreground hover:text-foreground hover:bg-muted/50'"
 @click="scrollTo(section.id)"
 >
 <span v-if="section.icon" class="mr-2":class="section.icon" />
 {{ section.label }}
 </button>
 </nav>
 </aside>
 <!-- 右侧内容 -->
 <div class="flex-1 min-w-0 space-y-6">
 <slot />
 </div>
 </div>
</template>
