<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'

/**
 * 运维大盘三视图顶部导航（总览 / 告警事件 / 系统日志）。
 *
 * 仅依赖路由路径字符串（不 import 75-02/03/04 页面文件），故可在 wave 1 独立产出。
 * 用 useRoute().path 高亮当前项；移动端可横向滚动不溢出，focus-visible 可见环。
 */
const route = useRoute()

interface TabItem {
  to: string
  label: string
  icon: string
}

const tabs: TabItem[] = [
  { to: '/admin/observability', label: '总览', icon: 'icon-[lucide--layout-dashboard]' },
  { to: '/admin/observability/alerts', label: '告警事件', icon: 'icon-[lucide--bell-ring]' },
  { to: '/admin/observability/logs', label: '系统日志', icon: 'icon-[lucide--scroll-text]' },
]

function isActive(to: string): boolean {
  // 总览为精确匹配（避免被 /alerts、/logs 前缀误高亮）；子页用前缀匹配。
  if (to === '/admin/observability')
    return route.path === to
  return route.path === to || route.path.startsWith(`${to}/`)
}
</script>

<template>
  <nav
    class="inline-flex items-center gap-1 overflow-x-auto rounded-md bg-muted p-1"
    aria-label="运维视图导航"
  >
    <RouterLink
      v-for="tab in tabs"
      :key="tab.to"
      :to="tab.to"
      :aria-current="isActive(tab.to) ? 'page' : undefined"
      class="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-transparent px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-[color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      :class="isActive(tab.to)
        ? 'bg-background text-foreground shadow-sm'
        : 'text-foreground/70 hover:text-foreground'"
    >
      <span :class="tab.icon" class="text-base" />
      {{ tab.label }}
    </RouterLink>
  </nav>
</template>
