<script setup lang="ts">
/**
 * FeedbackFloatingButton —— 可拖动的全局悬浮反馈按钮。
 *
 * 位置用 VueUse useDraggable 拖动并持久化到 localStorage；区分拖动与点击，点击打开
 * FeedbackDialog。仅登录用户可见。挂载在 App.vue 以覆盖所有页面（含 /chat）。
 */
import { useI18n } from 'vue-i18n'
import FeedbackDialog from '~/components/feedback/FeedbackDialog.vue'
import { useAuthStore } from '~/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()

const fab = ref<HTMLElement | null>(null)
const dialogOpen = ref(false)

const FAB_SIZE = 56
const MARGIN = 20

function defaultPosition() {
  if (typeof window === 'undefined')
    return { x: 0, y: 0 }
  return {
    x: window.innerWidth - FAB_SIZE - MARGIN,
    y: window.innerHeight - FAB_SIZE - MARGIN * 4,
  }
}

const stored = useLocalStorage('feedback-fab-position', defaultPosition())

const { x, y, style, isDragging } = useDraggable(fab, {
  initialValue: stored.value,
  preventDefault: true,
})

// 拖动过程中标记，避免拖动结束误触发点击
let moved = false
watch(isDragging, (dragging) => {
  if (dragging)
    moved = false
})
watch([x, y], () => {
  if (isDragging.value)
    moved = true
  stored.value = { x: x.value, y: y.value }
})

function clampIntoView() {
  if (typeof window === 'undefined')
    return
  const maxX = window.innerWidth - FAB_SIZE - MARGIN / 2
  const maxY = window.innerHeight - FAB_SIZE - MARGIN / 2
  x.value = Math.min(Math.max(MARGIN / 2, x.value), Math.max(MARGIN / 2, maxX))
  y.value = Math.min(Math.max(MARGIN / 2, y.value), Math.max(MARGIN / 2, maxY))
}

function handleClick() {
  if (moved) {
    moved = false
    return
  }
  dialogOpen.value = true
}

onMounted(() => {
  clampIntoView()
  window.addEventListener('resize', clampIntoView)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', clampIntoView)
})
</script>

<template>
  <template v-if="authStore.isAuthenticated">
    <button
      ref="fab"
      type="button"
      :style="style"
      class="fixed z-50 flex h-14 w-14 cursor-grab touch-none items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-shadow hover:shadow-xl active:cursor-grabbing"
      :class="{ 'cursor-grabbing shadow-2xl': isDragging }"
      :title="t('feedback.fab')"
      :aria-label="t('feedback.fab')"
      @click="handleClick"
    >
      <span class="icon-[lucide--message-square-plus] text-2xl" />
    </button>

    <FeedbackDialog v-model:open="dialogOpen" />
  </template>
</template>
