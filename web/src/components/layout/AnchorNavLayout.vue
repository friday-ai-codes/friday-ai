<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

export interface NavSection {
  id: string
  label: string
  icon?: string
  badge?: string | number
  badgeTone?: 'primary' | 'success' | 'warning' | 'danger' | 'muted'
}

const props = defineProps<{
  sections: NavSection[]
  /**
   * 滚动定位偏移（像素），点击时求值 —— 页面的 sticky 头高度可能随内容（如警示横幅）
   * 变化，静态常量会把段标题埋进头下。缺省沿用既有 88。
   */
  scrollOffset?: () => number
}>()

const activeSection = ref<string>(props.sections[0]?.id ?? '')
let observer: IntersectionObserver | null = null

/**
 * 观察窗上下沿占视口高度的百分比（`rootMargin` 与位置兜底共用同一对常量，
 * ⛔ 不要两处各写一个字面量——改了一处忘另一处会让兜底算错死区边界）。
 * 用整数百分比而不是 0.15 / 0.55：`0.55 * 100` 在浮点下是 55.00000000000001。
 */
const BAND_TOP_PERCENT = 15
const BAND_BOTTOM_PERCENT = 55

/**
 * 位置兜底：观察窗掐掉了视口上 15% / 下 55%，文档首尾各留了一段谁都不相交的死区。
 * 取观察窗上沿**之上**最近的那一段；全都在下方（滚到顶部）则回到第一段。
 */
function syncByPosition() {
  const bandTop = window.innerHeight * (BAND_TOP_PERCENT / 100)
  let candidate = props.sections[0]?.id ?? ''
  for (const section of props.sections) {
    const el = document.getElementById(section.id)
    if (el && el.getBoundingClientRect().top <= bandTop)
      candidate = section.id
  }
  activeSection.value = candidate
}

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter(e => e.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
      if (visible.length > 0) {
        activeSection.value = visible[0].target.id
        return
      }
      // ⛔ 不能直接 return 保留旧值：滚回顶部时没有任何段与观察窗相交，高亮会冻在离开前
      // 那一段，导航就在说谎（与「永远停在第一段」是同一类失守，只是方向相反）。
      syncByPosition()
    },
    {
      rootMargin: `-${BAND_TOP_PERCENT}% 0px -${BAND_BOTTOM_PERCENT}% 0px`,
      threshold: [0, 0.25, 0.5, 0.75, 1],
    },
  )

  props.sections.forEach((section) => {
    const el = document.getElementById(section.id)
    if (el)
      observer?.observe(el)
  })
})

onUnmounted(() => {
  observer?.disconnect()
})

function scrollTo(id: string) {
  const el = document.getElementById(id)
  if (!el)
    return
  const offset = props.scrollOffset?.() ?? 88
  const top = el.getBoundingClientRect().top + window.scrollY - offset
  window.scrollTo({ top, behavior: 'smooth' })
}

function badgeClass(section: NavSection, isActive: boolean) {
  if (isActive) {
    return 'bg-primary/15 text-primary'
  }
  const tone = section.badgeTone ?? 'muted'
  const map: Record<string, string> = {
    primary: 'bg-primary/10 text-primary',
    success: 'bg-emerald-500/10 text-emerald-600',
    warning: 'bg-amber-500/10 text-amber-600',
    danger: 'bg-destructive/10 text-destructive',
    muted: 'bg-muted text-muted-foreground',
  }
  return map[tone]
}
</script>

<template>
  <div class="flex gap-8">
    <!-- 左侧导航 -->
    <aside class="hidden md:block w-48 shrink-0">
      <nav class="sticky top-22 space-y-0.5">
        <button
          v-for="section in sections"
          :key="section.id"
          class="group relative w-full text-left pl-4 pr-2.5 py-2 rounded-md text-sm transition-colors flex items-center gap-2"
          :class="activeSection === section.id
            ? 'bg-primary/8 text-primary font-medium'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'"
          @click="scrollTo(section.id)"
        >
          <span
            v-if="activeSection === section.id"
            class="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-0.5 rounded-r-full bg-primary"
          />
          <span
            v-if="section.icon"
            :class="[section.icon, activeSection === section.id ? 'opacity-100' : 'opacity-70 group-hover:opacity-100']"
          />
          <span class="flex-1 truncate">{{ section.label }}</span>
          <span
            v-if="section.badge !== undefined && section.badge !== null && section.badge !== ''"
            class="ml-auto inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-[11px] font-medium leading-none transition-colors"
            :class="badgeClass(section, activeSection === section.id)"
          >
            {{ section.badge }}
          </span>
        </button>
      </nav>
    </aside>

    <!-- 右侧内容 -->
    <div class="flex-1 min-w-0 space-y-6">
      <slot />
    </div>
  </div>
</template>
