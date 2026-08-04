<script setup lang="ts">
import FeedbackHeaderButton from '~/components/feedback/FeedbackHeaderButton.vue'
import AppSidebar from '~/components/layout/AppSidebar.vue'
import GitHubStarButton from '~/components/layout/GitHubStarButton.vue'
import SystemHealthPopover from '~/components/layout/SystemHealthPopover.vue'
import NotificationBell from '~/components/notifications/NotificationBell.vue'
import { Toaster } from '~/components/ui/sonner'
import { useMobileSidebar } from '~/composables/useMobileSidebar'
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

// `< lg` 全局侧栏收成 off-canvas，各 header 左侧渲染汉堡按钮唤起
const { open: openMobileSidebar } = useMobileSidebar()

// 从 route.meta 获取页面标题
const pageTitle = computed(() => {
  const meta = route.meta as { title?: string }
  return meta.title || ''
})

// 项目详情页（作战室大盘）走「全屏应用」布局：锁定视口高度、内部各自滚动，
// 与 /chat 一致的沉浸式风格（保留全局顶栏）。匹配 /projects/<id>，不含列表页。
const isProjectWorkspace = computed(() => /^\/projects\/[^/]+$/.test(route.path))
</script>

<template>
  <div class="min-h-screen flex bg-background">
    <!-- 统一侧边栏 -->
    <AppSidebar />

    <!-- 主内容区域 -->
    <Transition name="mode-content" mode="out-in">
      <!-- Chat 路由：锁定视口高度，页面内部各自滚动（会话列表 / 消息区），
           顶部条与输入框固定不随页面滚动 -->
      <div v-if="route.path === '/chat'" key="content-chat" class="relative flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
        <!-- chat 分支无全局顶栏：`< lg` 用悬浮汉堡唤起 off-canvas 侧栏 -->
        <button
          type="button"
          class="absolute left-3 top-3 z-30 rounded-lg border border-border/60 bg-background/90 p-2 text-muted-foreground shadow-sm backdrop-blur hover:text-foreground lg:hidden"
          aria-label="打开导航"
          @click="openMobileSidebar"
        >
          <span class="icon-[lucide--menu] text-lg" />
        </button>
        <RouterView />
      </div>

      <!-- 项目作战室：全屏应用布局（锁定视口高度 + 保留全局顶栏 + 内部滚动） -->
      <div
        v-else-if="isProjectWorkspace"
        key="content-workspace"
        class="flex-1 flex flex-col min-w-0 h-screen overflow-hidden bg-background"
      >
        <header class="header-glass shrink-0 z-40 h-16">
          <div class="flex h-full items-center px-4 lg:px-6 gap-3">
            <button
              type="button"
              class="rounded-lg p-2 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors lg:hidden"
              aria-label="打开导航"
              @click="openMobileSidebar"
            >
              <span class="icon-[lucide--menu] text-lg" />
            </button>
            <div class="ml-auto flex items-center gap-3">
              <GitHubStarButton />
              <FeedbackHeaderButton />
              <NotificationBell />
              <SystemHealthPopover />
            </div>
          </div>
        </header>
        <main class="flex-1 min-h-0 overflow-hidden bg-mesh-gradient">
          <RouterView />
        </main>
      </div>

      <!-- 工作台路由 -->
      <div v-else key="content-friday" class="flex-1 flex flex-col min-w-0 bg-gray-50">
        <header class="header-glass sticky top-0 z-40 h-16">
          <div class="flex h-full items-center justify-between px-4 lg:px-6 gap-2">
            <div class="flex min-w-0 items-center gap-2">
              <button
                type="button"
                class="shrink-0 rounded-lg p-2 text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors lg:hidden"
                aria-label="打开导航"
                @click="openMobileSidebar"
              >
                <span class="icon-[lucide--menu] text-lg" />
              </button>
              <h1 v-if="pageTitle" class="truncate text-lg font-semibold text-foreground">
                {{ pageTitle }}
              </h1>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <GitHubStarButton />
              <FeedbackHeaderButton />
              <NotificationBell />
              <SystemHealthPopover />
            </div>
          </div>
        </header>

        <main class="flex-1 p-4 sm:p-6 bg-mesh-gradient">
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
