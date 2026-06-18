<script setup lang="ts">
import AppSidebar from '~/components/layout/AppSidebar.vue'
import SystemHealthPopover from '~/components/layout/SystemHealthPopover.vue'
import NotificationBell from '~/components/notifications/NotificationBell.vue'
import { Toaster } from '~/components/ui/sonner'
import { useNotificationsStore } from '~/stores/notifications'

// WebSocket 实时监控：保留自动连接逻辑；状态展示由 SystemHealthPopover 聚合
const { connect } = useRunnerMonitor()
// 站内信：初始化未读数 + 建立 WS（覆盖 /chat 分支不渲染顶栏铃铛的情况）
const notificationsStore = useNotificationsStore()
onMounted(() => {
  connect()
  notificationsStore.init().catch(() => {})
})

const route = useRoute()

// 从 route.meta 获取页面标题
const pageTitle = computed(() => {
  const meta = route.meta as { title?: string }
  return meta.title || ''
})
</script>

<template>
  <div class="min-h-screen flex bg-background">
    <!-- 统一侧边栏 -->
    <AppSidebar />

    <!-- 主内容区域 -->
    <Transition name="mode-content" mode="out-in">
      <!-- Chat 路由：锁定视口高度，页面内部各自滚动（会话列表 / 消息区），
           顶部条与输入框固定不随页面滚动 -->
      <div v-if="route.path === '/chat'" key="content-chat" class="flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
        <RouterView />
      </div>

      <!-- 工作台路由 -->
      <div v-else key="content-friday" class="flex-1 flex flex-col min-w-0 bg-gray-50">
        <header class="header-glass sticky top-0 z-40 h-16">
          <div class="flex h-full items-center justify-between px-6">
            <div>
              <h1 v-if="pageTitle" class="text-lg font-semibold text-foreground">
                {{ pageTitle }}
              </h1>
            </div>
            <div class="flex items-center gap-3">
              <NotificationBell />
              <SystemHealthPopover />
            </div>
          </div>
        </header>

        <main class="flex-1 p-6 bg-mesh-gradient">
          <RouterView />
        </main>
      </div>
    </Transition>
  </div>

  <Toaster rich-colors position="top-right" />
</template>

<style scoped>
.mode-content-enter-active {
  transition:
    opacity 0.3s ease,
    transform 0.3s ease;
}
.mode-content-leave-active {
  transition: opacity 0.15s ease;
}
.mode-content-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.mode-content-leave-to {
  opacity: 0;
}
</style>
