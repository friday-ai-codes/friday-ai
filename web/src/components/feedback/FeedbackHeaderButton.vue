<script setup lang="ts">
/**
 * FeedbackHeaderButton —— 顶栏右上角的反馈入口（替代原全局悬浮球，不再遮挡内容）。
 *
 * 样式对齐 NotificationBell 的顶栏图标按钮；点击打开 FeedbackDialog。仅登录用户可见。
 */
import { useI18n } from 'vue-i18n'
import FeedbackDialog from '~/components/feedback/FeedbackDialog.vue'
import { useAuthStore } from '~/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
const dialogOpen = ref(false)
</script>

<template>
  <template v-if="authStore.isAuthenticated">
    <button
      type="button"
      class="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-200 hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :class="{ 'bg-muted/60 text-foreground': dialogOpen }"
      :title="t('feedback.fab')"
      :aria-label="t('feedback.fab')"
      data-testid="feedback-header-btn"
      @click="dialogOpen = true"
    >
      <span class="icon-[lucide--message-square-plus] text-lg" />
    </button>

    <FeedbackDialog v-model:open="dialogOpen" />
  </template>
</template>
