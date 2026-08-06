<script setup lang="ts">
/**
 * 段导航条（quick-260806 布局整改：左栏纵向导航 → 头部横向导航）。
 *
 * ## 位置与吸顶
 *
 * 本组件作为 `BlueprintViewerHeader` 的 `nav` 插槽渲染在 **sticky 头部卡片内部**——
 * 与头部同卡吸顶，页面 `measureScrollOffset` 量 header `offsetHeight` 时天然把本条
 * 算进锚点跳转偏移，⛔ 不需要任何动态 top 计算。撤掉左侧竖栏后正文列拿回 ~200px。
 *
 * ## 两档形态（同一份 `sections`，恒 10 项，⛔ 不增删）
 *
 * - `< md`：Select 下拉（沿用原窄屏形态）；
 * - `≥ md`：横向 chip 条 + 滚动跟随高亮。IntersectionObserver 的观察窗常量与位置兜底
 *   自原 `AnchorNavLayout` 移植（该布局件仍服务其它两栏页面，本页不再使用）。
 *   observer 在 mount 那一刻按 `sections` 逐个 `getElementById` ⇒ **页面十段容器
 *   无条件渲染**是它挂上的前提（页面头注 ② 的硬约束，落点从布局件移到这里）。
 *
 * ## 高亮态双信号（e2e 依赖，⛔ 不要拆开）
 *
 * active chip 同时具备 `bg-primary/8` class 与 `span.absolute` 指示条 —— e2e 的
 * `activeNavIndex` 校验两个来源指向同一项，防止高亮被改成两套判定。
 */

import type { NavSection } from '~/components/layout/AnchorNavLayout.vue'
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const props = defineProps<{
  /** 与页面十段容器**同一个**数组（恒 10 项）。 */
  sections: NavSection[]
  /** 初始/深链选中段（query 驱动）；滚动跟随启动后由内部状态接管。 */
  activeId: string
}>()

const emit = defineEmits<{
  navigate: [sectionId: string]
}>()

const { t } = useI18n()

const active = ref<string>(props.activeId || props.sections[0]?.id || '')
const chipsEl = ref<HTMLElement | null>(null)

/** 深链 / query 变化仍能驱动高亮（如 `?section=` 一次性消费）。 */
watch(() => props.activeId, (id) => {
  if (id)
    active.value = id
})

// ── 滚动跟随（自 AnchorNavLayout 移植，常量同源）────────────────────────────────

/**
 * 观察窗上下沿占视口高度的百分比（`rootMargin` 与位置兜底共用同一对常量）。
 * 用整数百分比而不是 0.15 / 0.55：`0.55 * 100` 在浮点下是 55.00000000000001。
 */
const BAND_TOP_PERCENT = 15
const BAND_BOTTOM_PERCENT = 55

let observer: IntersectionObserver | null = null

/**
 * 位置兜底：观察窗掐掉了视口上 15% / 下 55%，文档首尾各留了一段谁都不相交的死区。
 * 取观察窗上沿**之上**最近的那一段；全都在下方（滚到顶部）则回到第一段。
 */
function syncByPosition(): void {
  const bandTop = window.innerHeight * (BAND_TOP_PERCENT / 100)
  let candidate = props.sections[0]?.id ?? ''
  for (const section of props.sections) {
    const el = document.getElementById(section.id)
    if (el && el.getBoundingClientRect().top <= bandTop)
      candidate = section.id
  }
  active.value = candidate
}

onMounted(() => {
  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter(e => e.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
      if (visible.length > 0) {
        active.value = visible[0].target.id
        return
      }
      // ⛔ 不能直接 return 保留旧值：滚回顶部时没有任何段与观察窗相交，高亮会冻在
      // 离开前那一段，导航就在说谎。
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

/** chip 条可横向滚动：高亮推进时把 active chip 滚进可视区（只动条内滚动，不动页面）。 */
watch(active, async (id) => {
  await nextTick()
  chipsEl.value
    ?.querySelector<HTMLElement>(`[data-section="${id}"]`)
    ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
})

// ── 交互 ─────────────────────────────────────────────────────────────────────

function onNavigate(sectionId: string): void {
  active.value = sectionId
  emit('navigate', sectionId)
}

function onSelectChange(value: string | number | bigint | Record<string, any> | null): void {
  if (typeof value === 'string' && value)
    onNavigate(value)
}

function badgeClass(section: NavSection, isActive: boolean): string {
  if (isActive)
    return 'bg-primary/15 text-primary'
  const tone = section.badgeTone ?? 'muted'
  const map: Record<string, string> = {
    primary: 'bg-primary/10 text-primary',
    success: 'bg-success/10 text-success-emphasis',
    warning: 'bg-warning/10 text-warning-emphasis',
    danger: 'bg-destructive/10 text-destructive',
    muted: 'bg-muted text-muted-foreground',
  }
  return map[tone]
}
</script>

<template>
  <div data-testid="blueprint-section-nav">
    <!-- < md：Select 下拉（原窄屏形态；sticky 由外层头部卡片承担） -->
    <div class="md:hidden" data-testid="blueprint-section-nav-select">
      <Select :model-value="active" @update:model-value="onSelectChange">
        <SelectTrigger class="h-9 w-full rounded-lg bg-background/90" :aria-label="t('knowledge.blueprints.viewer.sectionNavLabel')">
          <span class="icon-[lucide--list] mr-1.5 text-base text-muted-foreground" />
          <SelectValue :placeholder="t('knowledge.blueprints.viewer.sectionNavLabel')" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="section in sections" :key="section.id" :value="section.id">
            {{ section.label }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>

    <!-- ≥ md：横向 chip 条（溢出横滚、无滚动条；active chip 自动滚入可视区） -->
    <nav
      ref="chipsEl"
      class="scrollbar-hide hidden items-center gap-1 overflow-x-auto md:flex"
      :aria-label="t('knowledge.blueprints.viewer.sectionNavLabel')"
      data-testid="blueprint-section-nav-chips"
    >
      <button
        v-for="section in sections"
        :key="section.id"
        type="button"
        :data-section="section.id"
        class="relative flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors"
        :class="active === section.id
          ? 'bg-primary/8 text-primary font-medium'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'"
        @click="onNavigate(section.id)"
      >
        <!-- 高亮指示条（与 bg-primary/8 成对的第二信号，e2e 校验两者同项） -->
        <span
          v-if="active === section.id"
          class="absolute inset-x-2.5 bottom-0 h-0.5 rounded-full bg-primary"
        />
        <span class="whitespace-nowrap">{{ section.label }}</span>
        <span
          v-if="section.badge !== undefined && section.badge !== null && section.badge !== ''"
          class="inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-full px-1 text-[11px] font-medium leading-none transition-colors"
          :class="badgeClass(section, active === section.id)"
        >
          {{ section.badge }}
        </span>
      </button>
    </nav>
  </div>
</template>
