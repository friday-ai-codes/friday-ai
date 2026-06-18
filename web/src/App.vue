<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { ModalsContainer } from 'vue-final-modal'
import AnnouncementPopup from '~/components/announcements/AnnouncementPopup.vue'
import FeedbackFloatingButton from '~/components/feedback/FeedbackFloatingButton.vue'
import GlobalConfirmDialog from '~/components/GlobalConfirmDialog.vue'
import { usePermissionSync } from '~/composables/usePermissionSync'
import { useAuthStore } from '~/stores/auth'
import { useNotificationsStore } from '~/stores/notifications'

// 设置页面默认标题
useHead({
  title: 'Friday AI',
  meta: [
    { name: 'description', content: 'AI 驱动的敏捷开发自动化系统' },
  ],
})

// 全局权限同步：定期轮询检测权限变更
usePermissionSync()

// 登录态联动消息中心：登录后初始化（拉未读/弹窗 + 建 WS），登出后清理断连。
const authStore = useAuthStore()
const notificationsStore = useNotificationsStore()
watch(
  () => authStore.isAuthenticated,
  (authenticated) => {
    if (authenticated)
      notificationsStore.init().catch(() => {})
    else
      notificationsStore.reset()
  },
  { immediate: true },
)
</script>

<template>
  <RouterView />
  <ModalsContainer />
  <GlobalConfirmDialog />
  <FeedbackFloatingButton />
  <AnnouncementPopup />
</template>
